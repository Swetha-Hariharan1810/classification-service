all_criteria = {}


def register_criteria(criterion_):
    # register criteria
    all_criteria[criterion_.__name__] = criterion_
    return criterion_


@register_criteria
class SkipOnesideCall:
    def __call__(self, trans: str):
        lines = trans.splitlines()
        if len(lines) <= 1:
            return False
        speaker_ids = [line.strip().split(":")[0] for line in lines]
        return all(x == speaker_ids[0] for x in speaker_ids)


@register_criteria
class SkipTooshortCall:
    def __init__(self, min_len=100):
        self.min_len = min_len

    def __call__(self, trans: str):
        # skip too short call if input string is shorter than min_len
        return len(trans.split()) < self.min_len
