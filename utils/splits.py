"""Temporal train/test split (stage 3).

A fleet-wide calendar cutoff, not a per-household split. The reason:

Day-ahead procurement covers the entire fleet for one shared future window. A
split of "the last X percent per household" would mean that training rows of
one household lie calendrically *after* test rows of another. The model would
then have access to information from the period it is supposed to predict -
for instance a cold snap that produces training data in one household and test
data in another. A fleet-wide cutoff rules that out.

The boundary day belongs to `train`, the test set is strictly the future.
"""

from __future__ import annotations

import pandas as pd

from utils import config
from utils.reporting import Reporter

SPLIT_COLUMN = "split"
TRAIN = "train"
TEST = "test"


def assign_split(rep: Reporter, panel: pd.DataFrame) -> pd.DataFrame:
    rep.step("Assign the temporal train/test split")

    cutoff = pd.Timestamp(config.SPLIT_CUTOFF)
    panel = panel.copy()
    panel[SPLIT_COLUMN] = pd.Categorical(
        (panel["date"] > cutoff).map({False: TRAIN, True: TEST}), categories=[TRAIN, TEST]
    )

    counts = panel[SPLIT_COLUMN].value_counts()
    labelled = panel[panel[config.TARGET_COL].notna()]
    labelled_counts = labelled[SPLIT_COLUMN].value_counts()

    rep.metric("Cutoff (last training day)", str(cutoff.date()))
    rep.metric("Rows train", int(counts.get(TRAIN, 0)))
    rep.metric("Rows test", int(counts.get(TEST, 0)))
    rep.metric("Test share of all rows", 100 * counts.get(TEST, 0) / len(panel), "%")
    rep.metric("Rows with a target value train", int(labelled_counts.get(TRAIN, 0)))
    rep.metric("Rows with a target value test", int(labelled_counts.get(TEST, 0)))
    rep.metric(
        "Test share of the labelled rows",
        100 * labelled_counts.get(TEST, 0) / max(len(labelled), 1),
        "%",
    )

    train_dates = panel.loc[panel[SPLIT_COLUMN] == TRAIN, "date"]
    test_dates = panel.loc[panel[SPLIT_COLUMN] == TEST, "date"]
    rep.metric("Training period", f"{train_dates.min().date()} to {train_dates.max().date()}")
    rep.metric("Test period", f"{test_dates.min().date()} to {test_dates.max().date()}")

    rep.check(
        "test starts strictly after the end of training",
        bool(test_dates.min() > train_dates.max()),
        f"{train_dates.max().date()} < {test_dates.min().date()}",
    )
    rep.check(
        "boundary day belongs to train",
        bool((panel.loc[panel["date"] == cutoff, SPLIT_COLUMN] == TRAIN).all()),
        "",
    )
    rep.check(
        "split column fully populated",
        int(panel[SPLIT_COLUMN].isna().sum()) == 0,
        "",
    )

    # A household appearing only in the test set would have no training
    # history - acceptable for a pooled model, not for a per-household one.
    train_hh = set(panel.loc[panel[SPLIT_COLUMN] == TRAIN, "Household_ID"])
    test_hh = set(panel.loc[panel[SPLIT_COLUMN] == TEST, "Household_ID"])
    rep.metric("Households in training", len(train_hh))
    rep.metric("Households in test", len(test_hh))
    only_test = sorted(test_hh - train_hh)
    only_train = sorted(train_hh - test_hh)
    if only_test:
        rep.note(f"Households only in the test set (without training history): {only_test}")
    if only_train:
        rep.note(
            f"{len(only_train)} households appear only in training - their recording ends "
            "before the cutoff"
        )

    rep.note(
        "A fleet-wide cutoff instead of 'the last X percent per household': otherwise "
        "training rows of one household would lie calendrically after test rows of another"
    )
    rep.raise_on_failures()
    return panel
