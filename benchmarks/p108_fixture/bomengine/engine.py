from .model import BomResult
from .normalize import normalize_inputs
from .impact import compute_impact
from .schedule import assembly_waves
def evaluate_bom(raw_components,raw_changes):
    initial,final,changes,removed,_=normalize_inputs(raw_components,raw_changes)
    return BomResult(final,changes,compute_impact(initial,final,changes,removed),removed,assembly_waves(final))
