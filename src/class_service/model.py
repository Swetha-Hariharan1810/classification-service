import io
import json
import logging
import os
import zipfile
from datetime import datetime
from pathlib import Path
from typing import List, Union
from functools import reduce

import torch
from pydantic import BaseModel

from .criterion import all_criteria
from .dict import Dictionary
from .gpt2_bpe_utils import Encoder
from .preprocess import aggregate_by_channel
from .s3_util import download_buffer

logger = logging.getLogger(__name__)


class MulticlassConfig(BaseModel):
    thresh_hold: float = 0.5
    model_url: str = os.getenv("CLASS_MODEL_URL")
    model_version: str = os.getenv("CLASS_MODEL_VERSION")
    model_name: str = os.getenv("CLASS_MODEL_NAME")

    join_pred: bool = False
    join_weights: List[float] = [1.4, 1.2, 1]
    join_th: List[float] = [0.2, 0.2, 0.5]
    blank_backoff: bool = False
    individual_th: List[float] = [0.5, 0.5, 0.5]

    multilevel: bool = True
    low_conf_th: float = 0.495
    # high_conf_th: float = 0.75
    prob_passover: float = 0.35
    max_positions: int = 5500

    skip_criteria: List[str] = ["SkipOnesideCall", "SkipTooshortCall"]


class Multiclass:
    def __init__(
        self,
        classifier: torch.jit.ScriptModule,
        bpe,
        src_dict,
        label_dict,
        config=MulticlassConfig(),
    ):
        self.bpe = bpe
        self.classifier = classifier
        self.max_positions = config.max_positions
        self.config = config
        self.src_dict = src_dict
        self.label_dict = label_dict
        self.skip_criteria = [all_criteria[c]() for c in config.skip_criteria]

        logger.debug("Loading codes mapping from codes_map.json")
        script_dir = os.path.dirname(__file__)
        with open(os.path.join(script_dir, "codes_map.json"), encoding="utf-8") as f:
            self.codes_map = json.load(f)

        with open(os.path.join(script_dir, "exp_codes.json"), encoding="utf-8") as f:
            self.exp_codes = {
                k: (datetime.strptime(v.partition(':')[0], "%Y-%m-%d"), v.partition(':')[-1]) for k, v in json.load(f).items()
            }

        if config.blank_backoff:
            logger.debug("Loading blank codes map from blank_codes_map.json")
            with open(
                os.path.join(script_dir, "blank_codes.json"), encoding="utf-8"
            ) as f:
                self.blank_codes = json.load(f)
            with open(
                os.path.join(script_dir, "common_codes.json"), encoding="utf-8"
            ) as f:
                self.common_codes = json.load(f)
        with open(
            os.path.join(script_dir, "incomplete_codes.json"),
            encoding="utf-8",
        ) as f:
            self.incomplete_codes = set(json.load(f))
        self.id2label = {}
        self.label2id = {}
        label_id = 0
        for idx in range(len(self.label_dict)):
            label = self.label_dict[idx]
            if label not in [
                "<s>",
                "<pad>",
                "</s>",
                "<unk>",
                "<mask>",
            ] and not label.startswith("madeupword"):
                self.id2label[label_id] = label
                self.label2id[label] = label_id
                label_id += 1
        logger.debug(f"number of classes: {label_id}")

        self.children, self.level_masks = self.get_children()
        if config.join_pred:
            self.join_weights = torch.tensor(self.config.join_weights)
            self.join_th_weighted = (
                torch.log(torch.tensor(self.config.join_th)) * self.join_weights
            ).sum(-1)

    def get_children(self):
        num_labels = len(self.id2label)
        children = torch.zeros(num_labels, num_labels, dtype=torch.long)
        level_masks = torch.zeros(3, num_labels)
        for idx, label in self.id2label.items():
            levels = label.split("--")
            if len(levels) == 2:
                parent = self.label2id[levels[0]]
                children[parent][idx] = 1
            if len(levels) == 3:
                lv2_parent_code = "--".join(levels[:2])
                if lv2_parent_code in self.label2id:
                    lv2_parent = self.label2id[lv2_parent_code]
                    children[lv2_parent][idx] = 1
                lv1_parent = self.label2id[levels[0]]
                children[lv1_parent][idx] = 1
            level_masks[len(levels) - 1][idx] = 1
        return children, level_masks

    @torch.no_grad()
    def encode(self, text_ip: List[str], preprocess=True) -> torch.Tensor:
        if preprocess:
            text_ip = [aggregate_by_channel(tt) for tt in text_ip]
        transcript_bpes = [
            "<s> " + " ".join([str(b) for b in self.bpe.encode(text)]) + " </s>"
            for text in text_ip
        ]
        tokens_list = [
            self.src_dict.encode_line(t, append_eos=False) for t in transcript_bpes
        ]

        # truncate tokens longer than max_positions

        tokens_trunc = [
            torch.cat(
                [
                    tokens[:1],
                    tokens[max(len(tokens) - self.max_positions + 1, 1) :],
                ]
            )
            for tokens in tokens_list
        ]
        tokens = torch.nn.utils.rnn.pad_sequence(
            tokens_trunc, batch_first=True, padding_value=self.src_dict.pad()
        )
        return tokens

    @torch.no_grad()
    def inference(self, tokens: torch.Tensor) -> torch.Tensor:
        logits = self.classifier(tokens).detach()
        probs = torch.nn.Sigmoid()(logits)
        # shape (batch, num_classes)
        assert (probs >= 0).all(), logits
        assert (probs <= 1).all(), logits
        return probs

    def update_join_logits(self, probs):
        result_probs = torch.zeros(probs.shape)
        for lv3_idx in self.level_masks[2].nonzero().squeeze().tolist():
            lv3_label = self.id2label[lv3_idx]
            lv2_label = lv3_label[: lv3_label.rfind("--")]
            lv2_idx = self.label2id[lv2_label]
            lv1_label = lv3_label[: lv3_label.find("--")]
            lv1_idx = self.label2id[lv1_label]
            log_probs = torch.log(probs[:, [lv1_idx, lv2_idx, lv3_idx]])
            weights = self.join_weights.expand(probs.size(0), 3)
            assert log_probs.shape == weights.shape
            result_probs[:, lv3_idx] = (log_probs * weights).sum(-1)
        return result_probs

    def blank_backoff(self, label: str):
        parts = [p for p in label.split("--") if p != "##NA"]
        if len(parts) < 3:
            root_code = "--".join(parts)
            if root_code in self.incomplete_codes:
                return root_code
            if "##NA" in label:
                return root_code + "--" + self.blank_codes[root_code]
            else:
                return root_code + "--" + self.common_codes[root_code]

        assert "##NA" not in label
        return label

    def blank_filter(self, label: str):
        parts = [p for p in label.split("--") if p != "##NA"]
        if len(parts) < 3:
            root_code = "--".join(parts)
            if root_code not in self.incomplete_codes:
                return False
        return True

    def filter_expire(self, label_list, time_now):
        for label in label_list:
            for code in self.exp_codes.keys():
                if code in label and self.exp_codes[code][0] < time_now:
                    # check if a substitute code is available
                    if self.exp_codes[code][1]:
                        yield self.exp_codes[code][1]
                    break
            else:
                yield label

    def convert_to_prod(self, codes: List[str]):
        # remove duplicate codes
        new_codes = []
        for c in codes:
            if "--##NA" in c:
                root_c = c[: c.find("--##NA")]
                for other in codes:
                    if other != c and root_c in other:
                        break
                else:
                    new_codes.append(c)
            else:
                new_codes.append(c)
        result_labels = []
        level_labels = [[], [], []]
        if self.config.blank_backoff:
            new_codes = list(map(self.blank_backoff, new_codes))
        else:
            new_codes = list(filter(self.blank_filter, new_codes))
        time_now = datetime.now()
        for label in self.filter_expire(new_codes, time_now):
            result = ["", "", ""]
            for idx, label_part in enumerate(label.split("--")):
                if label_part != "##NA":
                    try:
                        prod_label = self.codes_map[label_part]
                    except KeyError:
                        logger.error(f"{label_part} not found in production code map.")
                        prod_label = ""

                    result[idx] = prod_label
                    level_labels[idx].append(prod_label)
            result_labels.append(result)

        return result_labels, level_labels

    def decode(self, probs: torch.Tensor) -> List[List[str]]:
        if self.config.join_pred:
            result_probs = self.update_join_logits(probs)
            preds = (result_probs > self.join_th_weighted) & (self.level_masks[2] == 1)

        elif self.config.multilevel:
            logger.debug("Merging different levels of codes")
            # pass over very low confidence twice to level 3

            probs -= (
                (probs < self.config.low_conf_th).long() @ self.children > 0
            ).long() * self.config.prob_passover

            threshold = (
                self.level_masks[0] * self.config.individual_th[0]
                + self.level_masks[1] * self.config.individual_th[1]
                + self.level_masks[2] * self.config.individual_th[2]
            )
            preds = probs > threshold
        else:
            threshold = (
                self.level_masks[0] * self.config.individual_th[0]
                + self.level_masks[1] * self.config.individual_th[1]
                + self.level_masks[2] * self.config.individual_th[2]
            )
            preds = probs > threshold

        pred_codes = self.pred_to_codes(preds)
        return pred_codes

    def pred_to_codes(self, preds: torch.Tensor) -> List[List[str]]:
        preds = preds.long()
        assert self.children is not None
        assert self.level_masks is not None
        parent_preds = ((preds @ self.children.t()) > 0).long()
        preds -= parent_preds
        preds = preds > 0
        return [
            [self.id2label[idx] for idx in sample_preds.nonzero().squeeze(1).tolist()]
            for sample_preds in preds
        ]

    @classmethod
    def from_pretrained(
        cls,
        models_dir: Union[Path, str],
        config: MulticlassConfig = MulticlassConfig(),
    ):
        models_dir = Path(models_dir)
        model_zip_file = models_dir / f"{config.model_version}.zip"
        model_arc = None

        if model_zip_file.exists():
            logger.info(f"Loading model from local: {model_zip_file}")
            model_arc = zipfile.ZipFile(model_zip_file)
        else:
            if not config.model_url:
                raise ValueError("model_url is not set in config file!")
            logger.info(
                f"{model_zip_file} not exist, downloading model from"
                f" {config.model_url}"
            )
            model_arc = zipfile.ZipFile(
                io.BytesIO(download_buffer(config.model_url)), "r"
            )
        logger.info("Start loading models ...")

        try:
            bpe_data = model_arc.read("bpe/vocab.bpe").decode("utf-8")
            encoder_json = json.loads(model_arc.read("bpe/encoder.json"))
            bpe_merges = [
                tuple(merge_str.split()) for merge_str in bpe_data.split("\n")[1:-1]
            ]
            bpe_model = Encoder(encoder=encoder_json, bpe_merges=bpe_merges)

            src_dict = Dictionary.load_from_buffer(model_arc.read("input0/dict.txt"))
            label_dict = Dictionary.load_from_buffer(model_arc.read("label/dict.txt"))
            model_jit = torch.jit.load(
                io.BytesIO(model_arc.read(f"{config.model_name}.pt"))
            )
        except KeyError as e:
            logger.exception(model_arc.infolist())
            raise e
        model_jit = torch.jit.optimize_for_inference(model_jit)

        class_model = cls(model_jit, bpe_model, src_dict, label_dict, config)
        logger.info("Finish loading models ...")
        return class_model
    
def get_class_codes(text: str, model: Multiclass, preprocess=True) -> List[List[str]]:
    # helper function to get codes from text
    if any(c(text) for c in model.skip_criteria):
        return [], [[], [], []]
    tokens = model.encode([text], preprocess)
    probs = model.inference(tokens)
    labels = model.decode(probs)[0]

    result_labels, level_labels = model.convert_to_prod(labels)
    return result_labels, level_labels


if __name__ == "__main__":
    import argparse

    import pandas as pd

    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument(
        "--model-dir",
        "-d",
        required=True,
        type=str,
        help="Directory that contains the model",
    )
    parser.add_argument(
        "--model-version", "-v", required=True, type=str, help="Model version"
    )
    parser.add_argument(
        "--model-name",
        "-n",
        required=True,
        type=str,
        help="Model name to look for.",
    )
    parser.add_argument(
        "--preprocess",
        "-p",
        action="store_true",
        help="set this option to do preprocess",
    )
    parser.add_argument("input_files", type=str, nargs="+", help="Input files")

    parser.add_argument(
        "--output",
        "-o",
        type=str,
        required=False,
        default="results.csv",
        help="output csv to write result to",
    )
    parser.add_argument("--debug", action="store_true", required=False, default=False)
    parser.add_argument(
        "--cpu-workers", type=int, default=1, help="Number of CPU workers"
    )
    args = parser.parse_args()
    logging.basicConfig(format="%(asctime)s - %(levelname)s - %(name)s - %(message)s")
    if args.debug:
        logger.setLevel(logging.DEBUG)
    torch.set_num_threads(args.cpu_workers)
    config = MulticlassConfig()
    config.model_version = args.model_version
    config.model_name = args.model_name

    model = Multiclass.from_pretrained(args.model_dir, config)
    result_codes = []
    for filename in args.input_files:
        text = Path(filename).read_text()
        result_labels, level_labels = get_class_codes(text, model, args.preprocess)
        result_codes.append(
            {
                "predict": json.dumps(result_labels),
                "filename": filename,
                "level1": level_labels[0],
                "level2": level_labels[1],
                "level3": level_labels[2],
            }
        )

    logger.info(f"Write results to {args.output}")
    pd.DataFrame(result_codes).to_csv(args.output, index=False)
