# Synthetic Document Design References

The Saad extension fixtures use fictional names, organizations, identifiers,
addresses, and amounts. Their information hierarchy is informed by public,
real-world examples; no government seal, commercial logo, personal record, or
template artwork is copied.

References reviewed on 2026-07-18:

| Fixture | Public reference | Layout conventions reused |
|---|---|---|
| Pay statements | [IRS sample pay stubs](https://apps.irs.gov/app/understandingTaxes/whys/thm04/les03/media/is1_thm04_les03.pdf), [FDIC Money Smart Module 3](https://catalog.fdic.gov/catalog/sfc/servlet.shepherd/document/download/069t000000Bcgy8AAB) | Separate earnings and deductions, current/YTD columns, hours, rate, gross and net summary |
| Benefit letter | [SSA sample benefit-verification material](https://www.ssa.gov/pgm/verificationflyer2013.pdf) | Dated letter format, recipient address block, narrative verification, benefit summary and contact section |
| Employment verification | [HUD Verification of Employment form](https://www.hud.gov/sites/documents/19671_employment.pdf) | Employer certification, pay basis, hours, employment status and signature lines |
| Bank deposit statement | [CFPB Regulation E periodic-statement requirements](https://www.consumerfinance.gov/rules-policy/regulations/1005/9/), [CFPB checking-account guide](https://files.consumerfinance.gov/f/documents/cfpb_adult-fin-ed_consumer-guide-to-managing-your-checking-account.pdf) | Statement period, beginning/ending balances, deposits, withdrawals and running-balance activity |
| Property rent statement | [Massachusetts sample summary-process form](https://www.mass.gov/doc/summary-process-eviction-complaint-sample-form/download), [HUD rent-ledger guidance](https://www.hud.gov/sites/documents/HSG-06-01GC5GUID.PDF) | Tenant/property identifiers and dated charge/payment/balance ledger |
| Self-employment statement | [IRS Publication 583](https://www.irs.gov/publications/p583) | Monthly revenue and expense categories with a reconciled net total |
| Government ID | [Massachusetts ID requirements](https://www.mass.gov/info-details/massachusetts-identification-id-requirements) | Card hierarchy with photograph area, full legal name, DOB and expiration; all credential identifiers are intentionally omitted |

The visible synthetic notice remains deliberately prominent even though it is
not part of the reference layouts. This prevents a training fixture from being
mistaken for a genuine financial, benefit, employment, or housing document.

Transaction-level details that make the PDFs visually realistic remain in the
packet preview. The parser copies only the allowlisted summary values required
by the RealDoor workflow.
