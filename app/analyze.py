import argparse
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd
from scipy.stats import t
from app.common import LABELS, TICKETS, fallback_hierarchy
from app.report import write_report

def macro_f1(rows):
    scores = []
    for label in LABELS:
        tp = ((rows.expected == label) & (rows.label == label)).sum()
        fp = ((rows.expected != label) & (rows.label == label)).sum()
        fn = ((rows.expected == label) & (rows.label != label)).sum()
        scores.append(2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0)
    return sum(scores) / len(scores)

def macro_precision_recall(rows):
    precision, recall = [], []
    for label in LABELS:
        tp = ((rows.expected == label) & (rows.label == label)).sum()
        fp = ((rows.expected != label) & (rows.label == label)).sum()
        fn = ((rows.expected == label) & (rows.label != label)).sum()
        precision.append(tp / (tp + fp) if tp + fp else 0)
        recall.append(tp / (tp + fn) if tp + fn else 0)
    return sum(precision) / len(LABELS), sum(recall) / len(LABELS)

def analyze(folder):
    folder = Path(folder)
    requests = pd.read_json(folder / 'requests.json')
    attempts = pd.read_json(folder / 'attempts.json')
    runs = json.loads((folder / 'runs.json').read_text(encoding='utf-8'))
    config = json.loads((folder / 'config.json').read_text(encoding='utf-8'))
    rows = []
    for run in runs:
        select = lambda df: df[(df.scenario == run['scenario']) & (df.strategy == run['strategy']) & (df['repeat'] == run['repeat'])]
        q, a = select(requests), select(attempts)
        f = q[q.source == 'fallback']
        precision, recall = macro_precision_recall(f) if len(f) else (float('nan'), float('nan'))
        successful = q[q.quality_success]
        recovery = float('nan')
        if run['scenario'] == 'outage':
            end = run['config']['fault_start'] + run['config']['fault_duration']
            recovered = a[(a.started >= end) & a.valid_output]
            if len(recovered):
                recovery = recovered.finished.min() - end
        rows.append(dict(scenario=run['scenario'], strategy=run['strategy'], repeat=run['repeat'],
            success_rate=q.quality_success.mean(), primary_success_rate=((q.source == 'primary') & q.quality_success).mean(),
            fallback_usage_rate=(q.source == 'fallback').mean(), fallback_success_rate=((q.source == 'fallback') & q.quality_success).mean(),
            fallback_accuracy=f.quality_success.mean() if len(f) else float('nan'),
            fallback_macro_f1=macro_f1(f) if len(f) else float('nan'),
            fallback_precision=precision, fallback_recall=recall,
            human_review_rate=(q.label == 'human_review').mean(),
            p50=q.latency.quantile(.5), p95=q.latency.quantile(.95), p99=q.latency.quantile(.99),
            success_p95=successful.latency.quantile(.95) if len(successful) else float('nan'),
            scheduler_lag_p95=q.scheduler_lag.quantile(.95),
            recovery_seconds=recovery, retry_count=(a.attempt > 0).sum(), rejected_count=q.rejected.sum(),
            circuit_open_seconds=run['circuit_open_seconds'], requests_during_outage=run['requests_during_outage'],
            primary_calls=run['server_requests'],
            estimated_cost_per_request=(len(a)*config['cost_per_call'] + len(f)*config['fallback_cost'])/len(q)))
    metrics = pd.DataFrame(rows)
    metrics.to_csv(folder / 'metrics_per_run.csv', index=False)
    summary = []
    for (scenario, strategy), group in metrics.groupby(['scenario', 'strategy']):
        for metric in metrics.columns[3:]:
            values = group[metric].dropna()
            n = len(values)
            mean = values.mean()
            sd = values.std(ddof=1)
            margin = t.ppf(.975, n-1)*sd/n**.5 if n > 1 else float('nan')
            summary.append(dict(scenario=scenario, strategy=strategy, metric=metric, n=n,
                                mean=mean, std=sd, ci95_low=mean-margin, ci95_high=mean+margin))
    summary = pd.DataFrame(summary)
    summary.to_csv(folder / 'summary.csv', index=False)
    # ประเมินกฎสำรองบน Ticket ชุดเดียวกันทั้งหมด เพิ่มจากข้อมูลที่ใช้ fallback จริง
    fixed_rows = []
    for text, expected in TICKETS:
        label, tier = fallback_hierarchy(text)
        fixed_rows.append({'text': text, 'expected': expected, 'label': label, 'tier': tier})
    fixed = pd.DataFrame(fixed_rows)
    fixed['correct'] = fixed.expected == fixed.label
    fixed.to_csv(folder / 'fallback_fixed_set.csv', index=False)
    fixed_precision, fixed_recall = macro_precision_recall(fixed)
    fixed_metrics = {'accuracy': float(fixed.correct.mean()), 'macro_precision': fixed_precision,
                     'macro_recall': fixed_recall, 'macro_f1': macro_f1(fixed),
                     'coverage': float((fixed.label != 'human_review').mean()), 'n': len(fixed)}
    (folder / 'fallback_fixed_metrics.json').write_text(json.dumps(fixed_metrics, indent=2), encoding='utf-8')
    scenarios = ['normal', 'outage', 'latency', 'error10', 'error30', 'error50',
                 'rate_limit', 'malformed', 'empty', 'irrelevant', 'drift']
    for metric in ['success_rate', 'p50', 'p95', 'p99', 'primary_calls', 'fallback_accuracy',
                   'recovery_seconds', 'requests_during_outage', 'estimated_cost_per_request']:
        selected = metrics[metrics.scenario == 'outage'] if metric in ['recovery_seconds', 'requests_during_outage'] else metrics
        pivot = selected.pivot_table(index='scenario', columns='strategy', values=metric)
        if pivot.empty:
            continue
        pivot = pivot.reindex([s for s in scenarios if s in pivot.index])
        errors = summary[summary.metric == metric].copy()
        errors['margin'] = errors.ci95_high - errors['mean']
        error_table = errors.pivot(index='scenario', columns='strategy', values='margin').reindex(index=pivot.index, columns=pivot.columns).fillna(0)
        axis = pivot.plot.bar(figsize=(10, 5), rot=15, yerr=error_table, capsize=3)
        unit = ' (seconds)' if metric in ['p50', 'p95', 'p99', 'recovery_seconds'] else ''
        axis.set_ylabel(metric + unit)
        axis.set_title('Mean and 95% t-CI across repetitions: ' + metric)
        axis.legend(title='Strategy', bbox_to_anchor=(1.01, 1), loc='upper left')
        plt.tight_layout()
        plt.savefig(folder / f'{metric}.png', dpi=160)
        plt.close()
    events = pd.read_json(folder / 'server_events.jsonl', lines=True)
    events.groupby(['scenario', 'strategy', 'fault_type']).size().rename('count').reset_index().to_csv(
        folder / 'failure_taxonomy_counts.csv', index=False)
    outage = events[(events.scenario == 'outage') & (events['repeat'] == 0)].copy()
    if len(outage):
        outage['second'] = outage.arrived.clip(lower=0).astype(int)
        timeline = outage.groupby(['second', 'strategy']).size().unstack(fill_value=0)
        timeline = timeline.reindex(range(int(config['duration']) + 1), fill_value=0)
        axis = timeline.plot(marker='o', figsize=(9, 4))
        start = config['duration'] * .25
        axis.axvspan(start, start + config['duration'] * .35, color='red', alpha=.12, label='Outage')
        axis.legend(bbox_to_anchor=(1.01, 1), loc='upper left')
        plt.ylabel('Primary requests received / second')
        plt.title('First repetition only; requests binned by arrival time')
        plt.tight_layout()
        plt.savefig(folder / 'outage_timeline.png', dpi=160)
        plt.close()
    write_report(folder, metrics, summary, config, fixed_metrics)
    print(f'Tables and figures: {folder.resolve()}')

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('folder')
    analyze(parser.parse_args().folder)
