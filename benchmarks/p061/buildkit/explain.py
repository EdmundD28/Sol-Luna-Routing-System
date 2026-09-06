from .model import BuildPlan
def explain_plan(plan):
    if not isinstance(plan,BuildPlan): raise TypeError('plan must be a BuildPlan')
    out=['changed='+(','.join(plan.changed) if plan.changed else '-'),'impacted='+(','.join(plan.impacted) if plan.impacted else '-')]
    out += [f'batch[{i}]={",".join(b)}' for i,b in enumerate(plan.batches,1)]
    out += ['critical='+(','.join(plan.critical_path) if plan.critical_path else '-')+f':{plan.critical_cost}',f'total_cost={plan.total_cost}']
    return tuple(out)
