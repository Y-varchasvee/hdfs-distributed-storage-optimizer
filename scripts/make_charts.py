#!/usr/bin/env python3
"""Draw charts and write the results summary, directly from benchmarks/results/*.json.

Nothing is typed in by hand: a chart or figure can only show what an experiment recorded.
Charts use one axis each, thin marks, hairline grids and a palette checked for color-vision deficiency.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

PROJECT = Path(__file__).resolve().parent.parent
RESULTS = PROJECT / "benchmarks" / "results"
CHARTS = PROJECT / "benchmarks" / "charts"
SUMMARY = PROJECT / "documentation" / "RESULTS_SUMMARY.md"

BLUE, ORANGE, GRAY = "#2a78d6", "#eb6834", "#898781"
INK, SECONDARY, GRID, AXIS = "#0b0b0b", "#52514e", "#e1e0d9", "#c3c2b7"
MIB = 1024 * 1024

plt.rcParams.update(
    {
        "font.family": ["Helvetica Neue", "Arial", "DejaVu Sans"],
        "font.size": 10,
        "axes.edgecolor": AXIS,
        "axes.linewidth": 0.8,
        "axes.titlesize": 11,
        "axes.titleweight": "semibold",
        "axes.titlelocation": "left",
        "axes.labelcolor": SECONDARY,
        "text.color": INK,
        "xtick.color": SECONDARY,
        "ytick.color": SECONDARY,
        "xtick.major.size": 0,
        "ytick.major.size": 0,
        "axes.grid": True,
        "axes.grid.axis": "y",
        "grid.color": GRID,
        "grid.linewidth": 0.8,
        "axes.axisbelow": True,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.spines.left": False,
        "legend.frameon": False,
        "figure.dpi": 200,
        "savefig.bbox": "tight",
    }
)


def load(name: str) -> dict:
    return json.loads((RESULTS / f"{name}.json").read_text())


def save(fig, name: str) -> None:
    CHARTS.mkdir(parents=True, exist_ok=True)
    fig.savefig(CHARTS / f"{name}.svg")
    fig.savefig(CHARTS / f"{name}.png", dpi=220)
    plt.close(fig)


def mib(value: float) -> float:
    return value / MIB


def size_label(bytes_value: int | None) -> str:
    if bytes_value is None:
        return "whole"
    return f"{bytes_value // 1024} KiB" if bytes_value < MIB else f"{bytes_value // MIB} MiB"


def grouped_bars(ax, categories, series, *, fmt="{:.1f}", width=0.32):
    positions = range(len(categories))
    offset = (len(series) - 1) * width / 2
    for index, (label, values, color) in enumerate(series):
        xs = [p + index * (width + 0.02) - offset for p in positions]
        bars = ax.bar(xs, values, width, label=label, color=color)
        for bar, value in zip(bars, values, strict=True):
            ax.text(bar.get_x() + bar.get_width() / 2, value, fmt.format(value), ha="center", va="bottom", fontsize=8.5, color=SECONDARY)
    ax.set_xticks(list(positions), categories)


def chart_exact_duplicates():
    rows = load("B_exact_duplicates")["rows"]
    copies = sorted({r["copies"] for r in rows})
    raw = [next(r for r in rows if r["copies"] == c and r["mode"] == "raw") for c in copies]
    file = [next(r for r in rows if r["copies"] == c and r["mode"] == "file") for c in copies]
    fig, ax = plt.subplots(figsize=(6.4, 3.2))
    grouped_bars(
        ax,
        [f"{c} {'copy' if c == 1 else 'copies'} per file" for c in copies],
        [
            ("No deduplication", [mib(r["hdfs_space_consumed_bytes"]) for r in raw], GRAY),
            ("Whole-file deduplication", [mib(r["hdfs_space_consumed_bytes"]) for r in file], BLUE),
        ],
        fmt="{:.0f}",
    )
    ax.set_ylabel("HDFS space consumed (MiB)")
    ax.set_title("Exact duplicates: space measured by the NameNode, replication 3")
    ax.legend(loc="upper left")
    save(fig, "exact_duplicates_space")


def chart_chunk_tradeoff():
    rows = load("D_chunk_sizes")["rows"]
    chunked = [r for r in rows if r["mode"] == "chunk"]
    labels = [size_label(r["chunk_size"]) for r in chunked]
    panels = [
        ("Savings on this workload (%)", [r["savings_percent"] for r in chunked], "{:.1f}", None),
        ("Upload throughput (MiB/s)", [r["upload_throughput_mib_s.mean"] for r in chunked], "{:.1f}", ([r["upload_throughput_mib_s.mean"] - r["upload_throughput_mib_s.min"] for r in chunked], [r["upload_throughput_mib_s.max"] - r["upload_throughput_mib_s.mean"] for r in chunked])),
        ("NameNode objects (files, directories, blocks)", [r["namespace_objects.mean"] for r in chunked], "{:,.0f}", None),
    ]
    fig, axes = plt.subplots(1, 3, figsize=(10.2, 2.9))
    for ax, (title, values, fmt, err) in zip(axes, panels, strict=True):
        ax.bar(labels, values, 0.5, color=BLUE, yerr=err, ecolor=SECONDARY, error_kw={"linewidth": 1, "capsize": 2})
        top = [v + (err[1][i] if err else 0) for i, v in enumerate(values)]
        for index, value in enumerate(values):
            ax.text(index, top[index], fmt.format(value), ha="center", va="bottom", fontsize=8.5, color=SECONDARY)
        ax.set_title(title, fontsize=10)
        ax.tick_params(axis="x", labelsize=8.5)
    fig.supxlabel("Chunk size", fontsize=9.5, color=SECONDARY)
    fig.tight_layout()
    save(fig, "chunk_size_tradeoff")


def chart_before_after():
    rows = load("I_before_after")["rows"]
    labels = [("Whole-file" if r["mode"] == "file" else f"Chunk, {size_label(r['chunk_size'])}") for r in rows]
    fig, axes = plt.subplots(1, 2, figsize=(8.8, 3.1))
    grouped_bars(
        axes[0],
        labels,
        [
            ("Before", [mib(r["hdfs_space_consumed_before"]) for r in rows], GRAY),
            ("After", [mib(r["hdfs_space_consumed_after"]) for r in rows], BLUE),
        ],
        fmt="{:.0f}",
    )
    axes[0].set_title("NameNode space consumed (MiB)", fontsize=10)
    grouped_bars(
        axes[1],
        labels,
        [
            ("Before", [mib(r["disk_used_delta_before.mean"]) for r in rows], GRAY),
            ("After", [mib(r["disk_used_delta_after.mean"]) for r in rows], BLUE),
        ],
        fmt="{:.0f}",
    )
    axes[1].set_title("DataNode disk used, measured with du (MiB)", fontsize=10)
    handles, labels_ = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels_, loc="lower center", ncol=2, bbox_to_anchor=(0.5, -0.06))
    fig.tight_layout()
    save(fig, "before_after_optimization")


def chart_restore():
    rows = load("E_roundtrip")["rows"]
    names = {"raw": "No dedup", "file": "Whole-file", "chunk": "Chunk, 256 KiB"}
    fig, ax = plt.subplots(figsize=(5, 2.8))
    values = [r["restore_throughput_mib_s.mean"] for r in rows]
    errors = ([v - r["restore_throughput_mib_s.min"] for v, r in zip(values, rows, strict=True)], [r["restore_throughput_mib_s.max"] - v for v, r in zip(values, rows, strict=True)])
    ax.bar([names[r["mode"]] for r in rows], values, 0.42, color=BLUE, yerr=errors, ecolor=SECONDARY, error_kw={"linewidth": 1, "capsize": 3})
    for index, value in enumerate(values):
        ax.text(index, value + errors[1][index], f"{value:.0f}", ha="center", va="bottom", fontsize=9, color=SECONDARY)
    ax.set_ylabel("MiB/s")
    ax.set_title("Verified restore throughput (bars show the range)")
    save(fig, "restore_throughput")


def chart_boundary_shift():
    rows = load("D2_boundary_shift")["rows"]
    names = {
        "pg1342.truncate_90.txt": "Truncated to 90%",
        "pg1342.replace_mid_byte.txt": "One byte replaced",
        "pg1342.prefix_newline.txt": "One byte inserted at start",
    }
    fig, ax = plt.subplots(figsize=(6, 2.3))
    labels = [names[r["variant"]] for r in rows][::-1]
    values = [r["reuse_percent"] for r in rows][::-1]
    ax.barh(labels, values, 0.45, color=BLUE)
    ax.grid(axis="x")
    ax.grid(axis="y", visible=False)
    for index, value in enumerate(values):
        ax.text(value + 1.2, index, f"{value:.1f}%", va="center", fontsize=9, color=SECONDARY)
    ax.set_xlim(0, 110)
    ax.set_xlabel("Chunks reused from the original (%)")
    ax.set_title(f"Fixed-size chunking at {size_label(rows[0]['chunk_size'])}")
    save(fig, "boundary_shift")


def bytes_text(value: float) -> str:
    return f"{value / MIB:.2f} MiB"


def write_summary() -> None:
    env = json.loads((RESULTS / "environment.json").read_text())
    a, b, c, d, d2 = (load(n) for n in ("A_unique_files", "B_exact_duplicates", "C_many_names", "D_chunk_sizes", "D2_boundary_shift"))
    e, f, h, i = (load(n) for n in ("E_roundtrip", "F_shared_deletion", "H_replication", "I_before_after"))
    lines = [
        "# Results summary",
        "",
        "Generated by `scripts/make_charts.py` from `benchmarks/results/`. Do not edit by hand.",
        "",
        f"Run started {env['run_started']}. {env['deployment']} Hadoop {env['hadoop_version']}, {env['live_datanodes']} DataNodes, replication {env['default_replication']}, {env['machine']}.",
        "",
        "Savings below describe these workloads, in which duplicates were created on purpose. They do not predict savings on any real system. Throughput describes this laptop setup.",
        "",
        "## A. Unique files",
        "",
        "| Mode | Files | Logical bytes | Stored bytes | Savings | HDFS files |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for r in a["rows"]:
        lines.append(f"| {r['mode']} | {r['logical_files']} | {bytes_text(r['logical_bytes'])} | {bytes_text(r['stored_content_bytes'])} | {r['savings_percent']:.2f}% | {r['hdfs_file_count']} |")
    lines += ["", "## B. Exact duplicates", "", "| Copies per file | Mode | Logical | Stored | Savings | Ratio | HDFS space consumed | Upload MiB/s (mean, range) |", "|---:|---|---:|---:|---:|---:|---:|---:|"]
    for r in b["rows"]:
        lines.append(
            f"| {r['copies']} | {r['mode']} | {bytes_text(r['logical_bytes'])} | {bytes_text(r['stored_content_bytes'])} | {r['savings_percent']:.2f}% | {r['dedup_ratio']:.2f} | {bytes_text(r['hdfs_space_consumed_bytes'])} | "
            f"{r['upload_throughput_mib_s.mean']:.1f} ({r['upload_throughput_mib_s.min']:.1f} to {r['upload_throughput_mib_s.max']:.1f}) |"
        )
    r = c["rows"][0]
    lines += ["", "## C. One file, many names", "", f"{c['extra']['logical_names']} logical names for one authentic file: {bytes_text(r['logical_bytes'])} logical, {bytes_text(r['stored_content_bytes'])} stored, {r['hdfs_file_count']} HDFS file, savings {r['savings_percent']:.2f}%. All {r['verification.files_passed']} of {r['verification.files_checked']} names passed SHA-256 verification."]
    lines += ["", "## D. Chunk size trade-off", "", "| Mode | Chunk size | Stored | Savings | HDFS files | NameNode objects | Disk used (du) | Upload MiB/s |", "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for r in d["rows"]:
        lines.append(
            f"| {r['mode']} | {size_label(r['chunk_size'])} | {bytes_text(r['stored_content_bytes'])} | {r['savings_percent']:.2f}% | {r['hdfs_file_count']} | {r['namespace_objects.mean']:.0f} | {bytes_text(r['disk_used_delta.mean'])} | {r['upload_throughput_mib_s.mean']:.1f} |"
        )
    lines += ["", "## D2. Fixed-size chunking boundary shift", "", "| Variant | Chunks | Reused | Reuse |", "|---|---:|---:|---:|"]
    for r in d2["rows"]:
        lines.append(f"| {r['variant']} | {r['chunks_total']} | {r['chunks_reused']} | {r['reuse_percent']:.1f}% |")
    lines += ["", "## E. Restore and checksum", "", "| Mode | Files | Matching source SHA-256 | Restore MiB/s (mean, range) |", "|---|---:|---:|---:|"]
    for r in e["rows"]:
        lines.append(f"| {r['mode']} | {r['files']} | {r['files_matching_source_sha256']} | {r['restore_throughput_mib_s.mean']:.1f} ({r['restore_throughput_mib_s.min']:.1f} to {r['restore_throughput_mib_s.max']:.1f}) |")
    lines += ["", "## F. Deletion with shared content", "", "| Mode | Stored, 2 refs | Stored, after purging 1 | Survivor passes | Delete then restore passes | HDFS files after last purge |", "|---|---:|---:|---|---|---:|"]
    for r in f["rows"]:
        lines.append(f"| {r['mode']} | {bytes_text(r['stored_bytes_two_references'])} | {bytes_text(r['stored_bytes_after_purging_one'])} | {r['survivor_passes_sha256']} | {r['soft_delete_then_restore_passes_sha256']} | {r['hdfs_files_after_purging_last']} |")
    lines += ["", "## H. Replication", "", "| Step | Factor | Length | Space consumed | Multiplier | fsck average | Under-replicated | Converged in |", "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for r in h["rows"]:
        lines.append(f"| {r['step']} | {r['factor']} | {bytes_text(r['length_bytes'])} | {bytes_text(r['space_consumed_bytes'])} | {r['multiplier']:.2f} | {r['average_block_replication']} | {r['under_replicated_blocks']} | {f'{r["converged_in_s.mean"]:.1f} s' if r.get('converged_in_s.mean') else 'N/A'} |")
    lines += ["", f"Requesting a factor above the live DataNodes was refused: \"{h['extra']['rejected_over_limit']}\"", "", "## I. Before and after optimization", "", "| Mode | Files | Logical | Stored before / after | NameNode space before / after | Disk (du) before / after | HDFS files before / after | Files passing SHA-256 | Optimize time |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for r in i["rows"]:
        lines.append(
            f"| {r['mode']} {size_label(r['chunk_size']) if r['chunk_size'] else ''} | {r['files']} | {bytes_text(r['logical_bytes'])} | {bytes_text(r['stored_before'])} / {bytes_text(r['stored_after'])} | {bytes_text(r['hdfs_space_consumed_before'])} / {bytes_text(r['hdfs_space_consumed_after'])} | "
            f"{bytes_text(r['disk_used_delta_before.mean'])} / {bytes_text(r['disk_used_delta_after.mean'])} | {r['hdfs_files_before']} / {r['hdfs_files_after']} | {r['verification.files_passed']} of {r['verification.files_checked']} | {r['optimize_duration_s.mean']:.2f} s |"
        )
    failure_path = RESULTS / "J_failure_handling.json"
    if failure_path.exists():
        lines += ["", "## J. Real failures", "", "```json", json.dumps(json.loads(failure_path.read_text()), indent=2), "```"]
    SUMMARY.write_text("\n".join(lines) + "\n")


def main() -> None:
    chart_exact_duplicates()
    chart_chunk_tradeoff()
    chart_before_after()
    chart_restore()
    chart_boundary_shift()
    write_summary()
    print(f"charts in {CHARTS}; summary in {SUMMARY}")


if __name__ == "__main__":
    main()
