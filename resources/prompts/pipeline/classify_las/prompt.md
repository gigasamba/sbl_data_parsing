Classify a contract document: MSA | PSA | QAG | LOI | Amendment | Assignment Letter | Other.
MSA=Master Services Agreement (incl. Master Development SERVICES Agreement / MDSA) | PSA=Product Specific Agreement
QAG=Quality Agreement | LOI=Letter of Information (pre-contract, incl. 의향서/양해각서)
Amendment=modifies ANY existing contract type (MSA/PSA/QAG/LOI amendment all → Amendment)
Assignment Letter=Novation/Assignment/계약양도
Other=SoW, NDA, MTA, TTA, MOU, DR/Memo, Side Letter, Service Order, Supply Agreement, DocuSign audit, LOU, Partnering

PRIORITY: (1)body opening "THIS [X] AGREEMENT" >(2)body first-2000 full name >(3)title keyword >(4)amendment presence.
Novation → Assignment Letter.
Supply/Manufacturing/Partnering/Termination → Other.
DocuSign audit (opens with "Final Audit Report"/"Transaction ID") → Other.
DR/Memo/Before + type keyword → Other (a REPORT).
LOU ≠ LOI → LOU is Other.

CONF CAPS: all agree=0.90+ | ambiguity=0.80 | conflict=0.60 | DR/Memo=0.75.
Output STRICT JSON: {"class":"...","confidence":<float>}