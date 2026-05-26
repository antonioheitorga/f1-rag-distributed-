"""
Metrics Viewer — consulta métricas emitidas pelos workers no CloudWatch.

Lista todas as métricas do namespace F1RagHarness e mostra estatísticas
agregadas (sum / average / min / max) da última janela configurável.

Uso:
    python infra/metrics_viewer.py                    # janela default 5 min
    python infra/metrics_viewer.py --window 60        # última hora
    python infra/metrics_viewer.py --metric pdf_processed_success
    python infra/metrics_viewer.py --by-worker        # agrega por WorkerId
"""

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import boto3  # noqa: E402

from config import AWS_ENDPOINT_URL, CLOUDWATCH_NAMESPACE  # noqa: E402

NAMESPACE = CLOUDWATCH_NAMESPACE


def _list_metrics(cw, metric_name: str | None = None) -> list[dict]:
    """Lista todas as métricas (ou só uma específica) do namespace."""
    kwargs = {"Namespace": NAMESPACE}
    if metric_name:
        kwargs["MetricName"] = metric_name
    response = cw.list_metrics(**kwargs)
    return response.get("Metrics", [])


def _get_stats(cw, metric_name: str, dimensions: list, window_min: int) -> dict:
    """Pega estatísticas agregadas de uma métrica na janela dada."""
    end = datetime.now(timezone.utc)
    start = end - timedelta(minutes=window_min)
    response = cw.get_metric_statistics(
        Namespace=NAMESPACE,
        MetricName=metric_name,
        Dimensions=dimensions,
        StartTime=start,
        EndTime=end,
        Period=60,  # buckets de 1 min
        Statistics=["Sum", "Average", "Minimum", "Maximum", "SampleCount"],
    )
    points = response.get("Datapoints", [])
    if not points:
        return {"samples": 0}

    return {
        "samples": int(sum(p["SampleCount"] for p in points)),
        "sum": sum(p["Sum"] for p in points),
        "min": min(p["Minimum"] for p in points),
        "max": max(p["Maximum"] for p in points),
        "avg": sum(p["Average"] * p["SampleCount"] for p in points) / sum(p["SampleCount"] for p in points),
    }


def cmd_overview(cw, window_min: int, metric_filter: str | None) -> None:
    """Mostra resumo de todas as métricas do namespace, agregando por nome
    (todas as dimensões somadas)."""
    metrics = _list_metrics(cw, metric_filter)
    if not metrics:
        print(f"Nenhuma métrica encontrada no namespace '{NAMESPACE}'.")
        if metric_filter:
            print(f"(filtro: --metric {metric_filter})")
        return

    # Coleta nomes únicos
    names = sorted({m["MetricName"] for m in metrics})

    print(f"Namespace : {NAMESPACE}")
    print(f"Endpoint  : {AWS_ENDPOINT_URL}")
    print(f"Janela    : últimos {window_min} min")
    print()
    print(f"{'Métrica':<32} {'Samples':>8} {'Sum':>10} {'Min':>10} {'Avg':>10} {'Max':>10}")
    print("-" * 84)

    for name in names:
        # Pega estatísticas SEM filtro de dimensão = agrega tudo.
        # Mas CloudWatch get_metric_statistics exige dimensões exatas — pra
        # agregar precisamos somar manualmente por dimensão.
        all_dims = [m["Dimensions"] for m in metrics if m["MetricName"] == name]
        total_samples = 0
        total_sum = 0.0
        all_mins = []
        all_maxs = []
        weighted_avg_num = 0.0
        weighted_avg_den = 0

        for dims in all_dims:
            stats = _get_stats(cw, name, dims, window_min)
            if stats["samples"] == 0:
                continue
            total_samples += stats["samples"]
            total_sum += stats["sum"]
            all_mins.append(stats["min"])
            all_maxs.append(stats["max"])
            weighted_avg_num += stats["avg"] * stats["samples"]
            weighted_avg_den += stats["samples"]

        if total_samples == 0:
            print(f"{name:<32} {'0':>8}  (sem dados na janela)")
            continue

        avg = weighted_avg_num / weighted_avg_den
        print(f"{name:<32} {total_samples:>8} {total_sum:>10.1f} "
              f"{min(all_mins):>10.1f} {avg:>10.1f} {max(all_maxs):>10.1f}")


def cmd_by_worker(cw, window_min: int, metric_filter: str | None) -> None:
    """Mostra métricas agrupadas por WorkerId."""
    metrics = _list_metrics(cw, metric_filter)
    if not metrics:
        print(f"Nenhuma métrica encontrada no namespace '{NAMESPACE}'.")
        return

    print(f"Namespace : {NAMESPACE}")
    print(f"Janela    : últimos {window_min} min\n")

    # Agrupa por WorkerId
    by_worker: dict[str, dict[str, dict]] = {}
    for m in metrics:
        worker = next((d["Value"] for d in m["Dimensions"] if d["Name"] == "WorkerId"), "?")
        stats = _get_stats(cw, m["MetricName"], m["Dimensions"], window_min)
        if stats["samples"] == 0:
            continue
        by_worker.setdefault(worker, {})[m["MetricName"]] = stats

    if not by_worker:
        print("Sem dados na janela.")
        return

    for worker, ms in sorted(by_worker.items()):
        print(f"=== {worker} ===")
        for name, stats in sorted(ms.items()):
            print(f"  {name:<32} samples={stats['samples']:>4}  sum={stats['sum']:>8.1f}")
        print()


def main():
    parser = argparse.ArgumentParser(description="Visualiza métricas do F1RagHarness no CloudWatch.")
    parser.add_argument("--window", type=int, default=5, help="Janela em minutos (default 5).")
    parser.add_argument("--metric", type=str, default=None, help="Filtra por nome de métrica.")
    parser.add_argument("--by-worker", action="store_true", help="Agrupa por WorkerId.")
    args = parser.parse_args()

    cw = boto3.client("cloudwatch", endpoint_url=AWS_ENDPOINT_URL)

    if args.by_worker:
        cmd_by_worker(cw, args.window, args.metric)
    else:
        cmd_overview(cw, args.window, args.metric)


if __name__ == "__main__":
    main()
