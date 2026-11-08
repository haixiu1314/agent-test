"""Pandas 聚合真实报告结果，Matplotlib 输出可导出的静态分析图。"""

import io
import threading

_lock = threading.Lock()


def report_chart(data):
    import pandas as pd
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib import pyplot as plt

    frame = pd.DataFrame(
        [
            {
                "type": r["test_type"],
                "status": r["status"],
                "duration_ms": r["duration_ms"],
            }
            for r in data["results"]
        ],
        columns=["type", "status", "duration_ms"],
    )
    with _lock:
        fig, axes = plt.subplots(1, 2, figsize=(11, 4), layout="constrained")
        counts = frame.groupby("status").size()
        if len(counts):
            axes[0].bar(
                counts.index,
                counts.values,
                color=[
                    "#b42318" if x in ["failed", "error"] else "#294b9b"
                    for x in counts.index
                ],
            )
        axes[0].set_title("Observed result states")
        axes[0].tick_params(axis="x", rotation=25)
        axes[0].set_ylabel("Samples")
        durations = frame["duration_ms"].dropna()
        if len(durations):
            axes[1].hist(durations, bins=min(12, len(durations)), color="#294b9b")
        axes[1].set_title("Actual response latency")
        axes[1].set_xlabel("Milliseconds")
        axes[1].set_ylabel("Samples")
        fig.suptitle("AgentTestLab / " + data["task"]["id"][:8])
        stream = io.BytesIO()
        fig.savefig(stream, format="png", dpi=140)
        plt.close(fig)
    return stream.getvalue()
