# Every NCBITaxon CURIE in Mech records, against TaxonMech's seed scope

TaxonMech scope: 626048 taxa (curation/seed_scope.tsv at 4895ee09fec7), 14 of them retired by data/raw/ncbi_merged_ids.tsv and counted outside it.

A record file is one git tracks under a record glob. A record citation is one record citing one taxon, so a record citing three outside taxa is three citations and one record.

| Mech | HEAD | record files | distinct taxa cited | in scope | outside scope | record citations of an outside taxon | records citing an outside taxon |
|---|---|---:|---:|---:|---:|---:|---:|
| culturemech | 199cd9191881 | 6325 | 59 | 54 | 5 | 6 | 4 |
| mediaingredientmech | 0dac27846669 | 2956 | 1 | 0 | 1 | 1 | 1 |
| communitymech | fc0c501b9dea | 515 | 935 | 564 | 371 | 792 | 280 |
| traitmech | 0c20b4c82a8b | 1130 | 359 | 333 | 26 | 32 | 32 |
| proteintraitsmech | 8d08b33cfbee | 429421 | 9372 | 7433 | 1939 | 165160 | 75853 |
| antibioticmech | 9d3d0205b298 | 3105 | 238 | 195 | 43 | 198 | 151 |
| cellstructuremech | 3b1731a6325f | 1022 | 221 | 137 | 84 | 865 | 644 |
| habitatmech | 30fbe25f4c53 | 3209 | 6741 | 6171 | 570 | 1604 | 326 |
| naturalproductmech | 18ca5dd6b902 | 3136 | 2625 | 1572 | 1053 | 2433 | 1368 |
| pathwaymech | 9584009d4957 | 282 | 110 | 105 | 5 | 95 | 94 |
| dufmech | 5642a6453498 | 8296 | 94 | 82 | 12 | 39 | 28 |
| cmmmech | 8287b17e542a | 698 | 170 | 144 | 26 | 39 | 33 |
| aimech | 6fcaa4797e37 | 442 | 0 | 0 | 0 | 0 | 0 |

## Taxa outside the scope: 3731 distinct across the fleet

| taxon | records citing it | Mechs |
|---|---:|---|
| NCBITaxon:9606 | 53326 | antibioticmech, cellstructuremech, communitymech, dufmech, habitatmech, naturalproductmech, proteintraitsmech |
| NCBITaxon:10090 | 46415 | antibioticmech, cellstructuremech, dufmech, habitatmech, naturalproductmech, proteintraitsmech |
| NCBITaxon:3702 | 20064 | cellstructuremech, communitymech, dufmech, naturalproductmech, proteintraitsmech |
| NCBITaxon:559292 | 15684 | antibioticmech, cellstructuremech, cmmmech, dufmech, naturalproductmech, pathwaymech, proteintraitsmech, traitmech |
| NCBITaxon:7227 | 11482 | cellstructuremech, communitymech, dufmech, proteintraitsmech |
| NCBITaxon:6239 | 9878 | communitymech, dufmech, habitatmech, naturalproductmech, proteintraitsmech |
| NCBITaxon:10116 | 1015 | habitatmech, naturalproductmech, proteintraitsmech |
| NCBITaxon:36329 | 860 | cellstructuremech, dufmech, proteintraitsmech |
| NCBITaxon:1883 | 449 | cmmmech, communitymech, habitatmech, naturalproductmech |
| NCBITaxon:9913 | 437 | naturalproductmech, proteintraitsmech |
| NCBITaxon:284812 | 377 | antibioticmech, cellstructuremech, proteintraitsmech |
| NCBITaxon:2 | 271 | antibioticmech, cellstructuremech, communitymech, habitatmech, pathwaymech, proteintraitsmech |
| NCBITaxon:7955 | 263 | dufmech, habitatmech, proteintraitsmech |
| NCBITaxon:39947 | 166 | habitatmech, naturalproductmech, proteintraitsmech |
| NCBITaxon:1070528 | 118 | proteintraitsmech |
| NCBITaxon:3055 | 113 | cellstructuremech, communitymech, habitatmech, proteintraitsmech |
| NCBITaxon:412755 | 101 | proteintraitsmech |
| NCBITaxon:10665 | 88 | proteintraitsmech |
| NCBITaxon:46015 | 85 | proteintraitsmech |
| NCBITaxon:286 | 77 | cmmmech, communitymech, habitatmech, naturalproductmech |
| NCBITaxon:2759 | 74 | cellstructuremech, communitymech, proteintraitsmech |
| NCBITaxon:227321 | 68 | antibioticmech, naturalproductmech, proteintraitsmech |
| NCBITaxon:262177 | 68 | proteintraitsmech |
| NCBITaxon:2157 | 63 | cellstructuremech, communitymech, proteintraitsmech |
| NCBITaxon:237561 | 59 | antibioticmech, cellstructuremech, proteintraitsmech |
| NCBITaxon:330879 | 55 | antibioticmech, naturalproductmech, proteintraitsmech |
| NCBITaxon:10299 | 54 | proteintraitsmech |
| NCBITaxon:1386 | 53 | cmmmech, communitymech, habitatmech, naturalproductmech |
| NCBITaxon:9031 | 53 | dufmech, habitatmech, naturalproductmech, proteintraitsmech |
| NCBITaxon:1873 | 50 | communitymech, naturalproductmech |
| NCBITaxon:10360 | 47 | proteintraitsmech |
| NCBITaxon:408172 | 46 | proteintraitsmech |
| NCBITaxon:212035 | 45 | proteintraitsmech |
| NCBITaxon:10377 | 43 | proteintraitsmech |
| NCBITaxon:295027 | 43 | proteintraitsmech |
| NCBITaxon:1177 | 42 | habitatmech, naturalproductmech |
| NCBITaxon:104245 | 41 | habitatmech |
| NCBITaxon:8355 | 40 | cellstructuremech, proteintraitsmech |
| NCBITaxon:36987 | 39 | habitatmech, proteintraitsmech |
| NCBITaxon:868565 | 32 | proteintraitsmech |
