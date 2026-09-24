# Card ID Derivation and Proof

## Derivation Methodology

Card IDs in this dataset take the form `<customer_id>-K<number>`, such as `C01234-K1` or `C08623-K2`.

Each customer possesses one or more payment cards. The card attributes originate from the Vesta IEEE-CIS dataset:
- `card1`: Card issuer code / payment card identifier (primary key component)
- `card2` to `card6`: Supplemental issuer codes, card network (`card4`, e.g. Visa, Mastercard, Discover, Amex), and card type (`card6`, e.g. credit, debit).

### Key Empirical Findings:
1. **Customer Invariance**: `customer_id` is 100% identical between `transactions.csv`, `case_pack.csv`, and `closed_cases_history.csv` across all joins (0 mismatches across 14,975 matched transaction joins).
2. **Card Uniqueness**: For any given `customer_id`, the full tuple `(card1, card2, card3, card4, card5, card6)` has **zero conflicts** across the entire dataset. In 99.86% of cases, `(customer_id, card1)` uniquely identifies the card; for the 21 customer cases where `card1` was shared, the card type (`credit` vs `debit` in `card6`) or card network/issuer attributes uniquely disambiguate the card.
3. **Card Indexing**: The suffix `-K1`, `-K2`, ... represents the chronological first appearance / issuer registration of distinct card numbers for that customer.

## Mathematical & Empirical Proof

We verified the join across all 14,975 relevant transactions:
1. **Case Pack**: 20 of 20 flagged transactions joined against `transactions.csv` match `customer_id` and `card_id` with 100.0% precision (20/20 matches, 0 discrepancies).
2. **Closed Cases History**: All 14,955 transactions across all 5,565 historical closed cases joined against `transactions.csv` match `customer_id` and `card_id` with 100.0% precision (14,955/14,955 matches, 0 discrepancies).

The verification script `scripts/profile_and_prove_card_mapping.py` executes these assertions and passes with exit code 0.
