"""Quick EDA: class imbalance, amount distributions, fraud by type & hour."""
from pathlib import Path
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PARQUET = PROJECT_ROOT / "data" / "processed" / "transactions.parquet"
OUT_DIR = PROJECT_ROOT / "data" / "processed" / "eda"


def main():
    df = pd.read_parquet(PARQUET)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    sns.set_style("whitegrid")

    print("\n=== Fraud rate by transaction type ===")
    by_type = df.groupby("type")["isFraud"].agg(["count", "sum", "mean"])
    by_type["fraud_pct"] = by_type["mean"] * 100
    print(by_type[["count", "sum", "fraud_pct"]].round(4))

    print("\n=== Imbalance ratio ===")
    pos = int(df["isFraud"].sum())
    neg = len(df) - pos
    print(f"Negatives : {neg:,}")
    print(f"Positives : {pos:,}")
    print(f"Ratio     : 1 : {neg / pos:.1f}")

    # Plot 1: imbalance
    fig, ax = plt.subplots(figsize=(6, 4))
    counts = df["isFraud"].value_counts()
    ax.bar(["Not fraud", "Fraud"], [counts.get(0, 0), counts.get(1, 0)],
           color=["#4C72B0", "#C44E52"])
    ax.set_yscale("log")
    ax.set_title(f"Class imbalance (fraud = {pos:,} / {len(df):,} = "
                 f"{100 * pos / len(df):.3f}%)")
    ax.set_ylabel("Count (log scale)")
    plt.tight_layout()
    plt.savefig(OUT_DIR / "class_imbalance.png", dpi=110)
    plt.close()

    # Plot 2: amount distribution (log) split by class
    fig, ax = plt.subplots(figsize=(8, 4))
    for label, color in [(0, "#4C72B0"), (1, "#C44E52")]:
        sub = df[df["isFraud"] == label]["amount"]
        sub = sub[sub > 0]
        if len(sub):
            ax.hist(sub, bins=60, alpha=0.55, label=f"isFraud={label}",
                    color=color, log=True)
    ax.set_xscale("log")
    ax.set_xlabel("Amount (log scale)")
    ax.set_ylabel("Count (log scale)")
    ax.set_title("Amount distribution by class")
    ax.legend()
    plt.tight_layout()
    plt.savefig(OUT_DIR / "amount_by_class.png", dpi=110)
    plt.close()

    # Plot 3: fraud rate by hour of day
    df["hour"] = df["step"] % 24
    hourly = df.groupby("hour")["isFraud"].mean() * 100
    fig, ax = plt.subplots(figsize=(8, 4))
    hourly.plot(kind="bar", ax=ax, color="#55A868")
    ax.set_ylabel("Fraud rate (%)")
    ax.set_title("Fraud rate by hour of day")
    plt.tight_layout()
    plt.savefig(OUT_DIR / "fraud_by_hour.png", dpi=110)
    plt.close()

    print(f"\nSaved EDA plots → {OUT_DIR}")


if __name__ == "__main__":
    main()