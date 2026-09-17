# classification-service

MDT-04-03 release
expiration codes file: x_medt2_csm_call_codes_3-29-2023.xlsx
## Install

```
cd src
pip install -e .
```

## Usage
```
python -m class_service.model -d v10-transbig -v v10tb-1.2-1.4_1.2_1-lr5e-05-u5075-f4 -n 1.2-1.4_1.2_1-lr5e-05-u5075-f4.ckpt.jit -p -o <output.csv> data/classification/test-mdt/inputs/*

```
