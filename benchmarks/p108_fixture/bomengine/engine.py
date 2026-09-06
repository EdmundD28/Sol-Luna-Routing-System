from .impact import compute_impact
from .model import BomResult
from .normalize import normalize_inputs
from .schedule import assembly_waves

def evaluate_bom(raw_components, raw_changes):
    initial, changes, final, removed = normalize_inputs(raw_components, raw_changes)
    impacted = compute_impact(initial, final, changes, removed)
    waves = assembly_waves(final)
    return BomResult(final, changes, impacted, removed, waves)
