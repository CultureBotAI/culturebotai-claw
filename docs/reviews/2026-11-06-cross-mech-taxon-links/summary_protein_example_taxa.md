# Protein-example taxa against TaxonMech's seed scope

TaxonMech scope: 626048 taxa (curation/seed_scope.tsv at 4895ee09fec7), 14 of them retired by data/raw/ncbi_merged_ids.tsv and counted outside it.

| Mech | HEAD | files | parsed | examples | distinct taxa | in scope | outside scope | malformed | no taxon |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| culturemech | 199cd9191881 | 6325 | 1 | 0 | 0 | 0 | 0 | 0 | 0 |
| mediaingredientmech | 0dac27846669 | 2956 | 23 | 0 | 0 | 0 | 0 | 0 | 0 |
| communitymech | fc0c501b9dea | 515 | 202 | 0 | 0 | 0 | 0 | 0 | 0 |
| traitmech | 0c20b4c82a8b | 1130 | 520 | 210 | 90 | 209 | 1 | 0 | 0 |
| proteintraitsmech | 8d08b33cfbee | 429421 | 142411 | 420162 | 9368 | 70116 | 298658 | 0 | 51388 |
| antibioticmech | 9d3d0205b298 | 3105 | 191 | 385 | 53 | 281 | 104 | 0 | 0 |
| cellstructuremech | 3b1731a6325f | 1022 | 621 | 2392 | 99 | 925 | 1467 | 0 | 0 |
| habitatmech | 30fbe25f4c53 | 3209 | 46 | 87 | 31 | 79 | 8 | 0 | 0 |
| naturalproductmech | 18ca5dd6b902 | 3136 | 3123 | 0 | 0 | 0 | 0 | 0 | 0 |
| pathwaymech | 9584009d4957 | 282 | 226 | 0 | 0 | 0 | 0 | 0 | 0 |
| dufmech | 5642a6453498 | 8296 | 95 | 0 | 0 | 0 | 0 | 0 | 0 |
| cmmmech | 8287b17e542a | 698 | 322 | 1198 | 47 | 1172 | 26 | 0 | 0 |
| aimech | 6fcaa4797e37 | 442 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

## Taxa outside the scope: 1947 distinct, 300264 examples

| taxon | label | examples | Mechs |
|---|---|---:|---|
| NCBITaxon:9606 | Homo sapiens | 100366 | antibioticmech, cellstructuremech, habitatmech, proteintraitsmech |
| NCBITaxon:10090 | Mus musculus | 90644 | cellstructuremech, proteintraitsmech |
| NCBITaxon:3702 | Arabidopsis thaliana | 46118 | cellstructuremech, proteintraitsmech |
| NCBITaxon:559292 | Saccharomyces cerevisiae (strain ATCC 204508 / S288c) | 23459 | antibioticmech, cellstructuremech, cmmmech, proteintraitsmech, traitmech |
| NCBITaxon:7227 | Drosophila melanogaster | 16794 | cellstructuremech, proteintraitsmech |
| NCBITaxon:6239 | Caenorhabditis elegans | 13126 | proteintraitsmech |
| NCBITaxon:36329 | Plasmodium falciparum (isolate 3D7) | 1078 | cellstructuremech, proteintraitsmech |
| NCBITaxon:10116 | Rattus norvegicus | 1022 | proteintraitsmech |
| NCBITaxon:284812 | Schizosaccharomyces pombe (strain 972 / ATCC 24843) | 546 | cellstructuremech, proteintraitsmech |
| NCBITaxon:9913 | Bos taurus | 445 | proteintraitsmech |
| NCBITaxon:7955 | Danio rerio | 264 | proteintraitsmech |
| NCBITaxon:39947 | Oryza sativa subsp. japonica | 180 | proteintraitsmech |
| NCBITaxon:3055 | Chlamydomonas reinhardtii | 127 | cellstructuremech, proteintraitsmech |
| NCBITaxon:1070528 | viral metagenome | 118 | proteintraitsmech |
| NCBITaxon:412755 | marine sediment metagenome | 101 | proteintraitsmech |
| NCBITaxon:10665 | Enterobacteria phage T4 | 93 | proteintraitsmech |
| NCBITaxon:46015 | Autographa californica nuclear polyhedrosis virus | 87 | proteintraitsmech |
| NCBITaxon:262177 | Orgyia pseudotsugata multicapsid polyhedrosis virus | 68 | proteintraitsmech |
| NCBITaxon:237561 | Candida albicans (strain SC5314 / ATCC MYA-2876) | 62 | antibioticmech, cellstructuremech, proteintraitsmech |
| NCBITaxon:212035 | Acanthamoeba polyphaga mimivirus | 59 | proteintraitsmech |
| NCBITaxon:10299 | Human herpesvirus 1 (strain 17) | 55 | proteintraitsmech |
| NCBITaxon:10360 | Human cytomegalovirus (strain AD169) | 52 | proteintraitsmech |
| NCBITaxon:9031 | Gallus gallus | 51 | proteintraitsmech |
| NCBITaxon:227321 | Emericella nidulans (strain FGSC A4 / ATCC 38163 / CBS 112.46 / NRRL 194 / M139) | 46 | proteintraitsmech |
| NCBITaxon:408172 | marine metagenome | 46 | proteintraitsmech |
| NCBITaxon:10377 | Epstein-Barr virus (strain B95-8) | 45 | proteintraitsmech |
| NCBITaxon:295027 | Human cytomegalovirus (strain Merlin) | 44 | proteintraitsmech |
| NCBITaxon:8355 | Xenopus laevis | 40 | cellstructuremech, proteintraitsmech |
| NCBITaxon:330879 | Aspergillus fumigatus (strain ATCC MYA-4609 / CBS 101355 / FGSC A1100 / Af293) | 37 | antibioticmech, proteintraitsmech |
| NCBITaxon:9823 | Sus scrofa | 35 | proteintraitsmech |
| NCBITaxon:2697049 | Severe acute respiratory syndrome coronavirus 2 | 34 | antibioticmech, proteintraitsmech |
| NCBITaxon:868565 | Human herpesvirus 8 type P (isolate GK18) | 32 | proteintraitsmech |
| NCBITaxon:10515 | Human adenovirus C serotype 2 | 30 | proteintraitsmech |
| NCBITaxon:2681603 | Escherichia phage Mu | 28 | proteintraitsmech |
| NCBITaxon:9541 | Macaca fascicularis | 27 | proteintraitsmech |
| NCBITaxon:11676 | Human immunodeficiency virus 1 | 26 | antibioticmech, proteintraitsmech |
| NCBITaxon:10254 | Vaccinia virus (strain Western Reserve) | 26 | proteintraitsmech |
| NCBITaxon:2681611 | Escherichia phage lambda | 26 | proteintraitsmech |
| NCBITaxon:284593 | Candida glabrata (strain ATCC 2001 / BCRC 20586 / JCM 3761 / NBRC 0622 / NRRL Y-65 / CBS 138) | 26 | antibioticmech, proteintraitsmech |
| NCBITaxon:284590 | Kluyveromyces lactis (strain ATCC 8585 / CBS 2359 / DSM 70799 / NBRC 1267 / NRRL Y-1140 / WM37) | 25 | proteintraitsmech |
