# Passenger Rejection & Timeout Analysis

## 1. The Core Issue: Flawed Assignment Logic
A deep dive into the code reveals **why** these passengers timed out.
In `evaluate_subset` (file2.py), when assigning a vehicle to a passenger, the algorithm calculates the cost, but **it never checks if the vehicle can actually reach the passenger before `W_max` (600s / 10 minutes)**.
As a result, the system happily assigns a passenger to an empty vehicle that is 15 minutes away across the city. The vehicle starts driving, but 10 minutes later, the passenger's wait timer expires and they reject the ride. The vehicle is then left driving empty (deadheading) toward a canceled trip, wasting time and fuel.

## 2. Spatial Density of Timeouts
We mapped the 1000m x 1000m grid regions where timeouts occurred most frequently. A high percentage of timeouts in a specific cell indicates that vehicles are either not rebalancing there, or are being dispatched from too far away.

| Grid Cell (1km x 1km) | Timeouts | Total Requests | Timeout Rate |
|---|---|---|---|
| (2, 4) | 272 | 862 | 31.6% |
| (1, 6) | 198 | 744 | 26.6% |
| (2, 8) | 107 | 566 | 18.9% |
| (1, 5) | 104 | 458 | 22.7% |
| (2, 5) | 98 | 464 | 21.1% |
| (3, 4) | 89 | 315 | 28.3% |
| (2, 9) | 70 | 379 | 18.5% |
| (1, 4) | 62 | 230 | 27.0% |
| (2, 7) | 52 | 385 | 13.5% |
| (3, 5) | 49 | 254 | 19.3% |
| (2, 6) | 41 | 204 | 20.1% |
| (3, 7) | 40 | 240 | 16.7% |
| (3, 6) | 33 | 268 | 12.3% |
| (1, 7) | 30 | 243 | 12.3% |
| (4, 8) | 30 | 316 | 9.5% |
| (3, 9) | 28 | 245 | 11.4% |
| (1, 9) | 23 | 37 | 62.2% |
| (3, 8) | 20 | 227 | 8.8% |
| (2, 3) | 20 | 55 | 36.4% |
| (5, 10) | 19 | 153 | 12.4% |

## 3. Detailed Rejection Log (First 100)
Below is a sample of specific passengers, the vehicle they were assigned, and why they timed out. You can cross-reference these `pID` values in the log file.

| Passenger ID | Time Requested | Assigned Vehicle | Reason |
|---|---|---|---|
| p31 | t=5.0s | v2984. | Vehicle took longer than 10 minutes to arrive. |
| p32 | t=6.0s | v1421. | Vehicle took longer than 10 minutes to arrive. |
| p34 | t=6.0s | v110. | Vehicle took longer than 10 minutes to arrive. |
| p39 | t=8.0s | v2513. | Vehicle took longer than 10 minutes to arrive. |
| p53 | t=11.0s | v357. | Vehicle took longer than 10 minutes to arrive. |
| p58 | t=13.0s | v1187. | Vehicle took longer than 10 minutes to arrive. |
| p69 | t=17.0s | v2325. | Vehicle took longer than 10 minutes to arrive. |
| p110 | t=30.0s | v110. | Vehicle took longer than 10 minutes to arrive. |
| p111 | t=30.0s | v2317. | Vehicle took longer than 10 minutes to arrive. |
| p132 | t=36.0s | v1732. | Vehicle took longer than 10 minutes to arrive. |
| p133 | t=36.0s | v1732. | Vehicle took longer than 10 minutes to arrive. |
| p134 | t=36.0s | v1732. | Vehicle took longer than 10 minutes to arrive. |
| p139 | t=37.0s | v2984. | Vehicle took longer than 10 minutes to arrive. |
| p140 | t=37.0s | v737. | Vehicle took longer than 10 minutes to arrive. |
| p157 | t=44.0s | v2375. | Vehicle took longer than 10 minutes to arrive. |
| p169 | t=47.0s | v2860. | Vehicle took longer than 10 minutes to arrive. |
| p188 | t=50.0s | v2904. | Vehicle took longer than 10 minutes to arrive. |
| p194 | t=50.0s | v328. | Vehicle took longer than 10 minutes to arrive. |
| p203 | t=54.0s | v2729. | Vehicle took longer than 10 minutes to arrive. |
| p204 | t=54.0s | v2729. | Vehicle took longer than 10 minutes to arrive. |
| p217 | t=55.0s | v1802. | Vehicle took longer than 10 minutes to arrive. |
| p218 | t=55.0s | v1802. | Vehicle took longer than 10 minutes to arrive. |
| p221 | t=55.0s | v153. | Vehicle took longer than 10 minutes to arrive. |
| p222 | t=55.0s | v153. | Vehicle took longer than 10 minutes to arrive. |
| p224 | t=56.0s | v1611. | Vehicle took longer than 10 minutes to arrive. |
| p242 | t=63.0s | v737. | Vehicle took longer than 10 minutes to arrive. |
| p255 | t=67.0s | v2904. | Vehicle took longer than 10 minutes to arrive. |
| p264 | t=70.0s | v461. | Vehicle took longer than 10 minutes to arrive. |
| p283 | t=74.0s | v72. | Vehicle took longer than 10 minutes to arrive. |
| p297 | t=79.0s | v1275. | Vehicle took longer than 10 minutes to arrive. |
| p319 | t=82.0s | v1616. | Vehicle took longer than 10 minutes to arrive. |
| p342 | t=85.0s | v2551. | Vehicle took longer than 10 minutes to arrive. |
| p387 | t=93.0s | v2404. | Vehicle took longer than 10 minutes to arrive. |
| p388 | t=93.0s | v2404. | Vehicle took longer than 10 minutes to arrive. |
| p395 | t=94.0s | v1211. | Vehicle took longer than 10 minutes to arrive. |
| p396 | t=94.0s | v2949. | Vehicle took longer than 10 minutes to arrive. |
| p399 | t=97.0s | v2470. | Vehicle took longer than 10 minutes to arrive. |
| p400 | t=97.0s | v1699. | Vehicle took longer than 10 minutes to arrive. |
| p412 | t=98.0s | v2375. | Vehicle took longer than 10 minutes to arrive. |
| p428 | t=103.0s | v2537. | Vehicle took longer than 10 minutes to arrive. |
| p429 | t=103.0s | v1699. | Vehicle took longer than 10 minutes to arrive. |
| p433 | t=106.0s | v2693. | Vehicle took longer than 10 minutes to arrive. |
| p449 | t=111.0s | v2470. | Vehicle took longer than 10 minutes to arrive. |
| p459 | t=116.0s | v1051. | Vehicle took longer than 10 minutes to arrive. |
| p470 | t=118.0s | v2664. | Vehicle took longer than 10 minutes to arrive. |
| p471 | t=118.0s | v2664. | Vehicle took longer than 10 minutes to arrive. |
| p472 | t=119.0s | v1314. | Vehicle took longer than 10 minutes to arrive. |
| p473 | t=120.0s | v1647. | Vehicle took longer than 10 minutes to arrive. |
| p477 | t=123.0s | v1254. | Vehicle took longer than 10 minutes to arrive. |
| p484 | t=124.0s | v488. | Vehicle took longer than 10 minutes to arrive. |
| p496 | t=127.0s | v1874. | Vehicle took longer than 10 minutes to arrive. |
| p502 | t=128.0s | v2641. | Vehicle took longer than 10 minutes to arrive. |
| p503 | t=128.0s | v2641. | Vehicle took longer than 10 minutes to arrive. |
| p504 | t=128.0s | v2641. | Vehicle took longer than 10 minutes to arrive. |
| p519 | t=130.0s | v1475. | Vehicle took longer than 10 minutes to arrive. |
| p523 | t=132.0s | v432. | Vehicle took longer than 10 minutes to arrive. |
| p524 | t=132.0s | v432. | Vehicle took longer than 10 minutes to arrive. |
| p530 | t=133.0s | v2860. | Vehicle took longer than 10 minutes to arrive. |
| p541 | t=138.0s | v2031. | Vehicle took longer than 10 minutes to arrive. |
| p563 | t=144.0s | v1187. | Vehicle took longer than 10 minutes to arrive. |
| p569 | t=144.0s | v2375. | Vehicle took longer than 10 minutes to arrive. |
| p571 | t=145.0s | v2862. | Vehicle took longer than 10 minutes to arrive. |
| p572 | t=145.0s | v2862. | Vehicle took longer than 10 minutes to arrive. |
| p574 | t=146.0s | v860. | Vehicle took longer than 10 minutes to arrive. |
| p575 | t=146.0s | v1012. | Vehicle took longer than 10 minutes to arrive. |
| p599 | t=150.0s | v1844. | Vehicle took longer than 10 minutes to arrive. |
| p600 | t=150.0s | v2840. | Vehicle took longer than 10 minutes to arrive. |
| p607 | t=153.0s | v1440. | Vehicle took longer than 10 minutes to arrive. |
| p625 | t=155.0s | v1654. | Vehicle took longer than 10 minutes to arrive. |
| p634 | t=162.0s | v2416. | Vehicle took longer than 10 minutes to arrive. |
| p659 | t=170.0s | v1440. | Vehicle took longer than 10 minutes to arrive. |
| p691 | t=175.0s | v1647. | Vehicle took longer than 10 minutes to arrive. |
| p693 | t=176.0s | v1342. | Vehicle took longer than 10 minutes to arrive. |
| p694 | t=176.0s | v1342. | Vehicle took longer than 10 minutes to arrive. |
| p724 | t=182.0s | v1208. | Vehicle took longer than 10 minutes to arrive. |
| p725 | t=182.0s | v1208. | Vehicle took longer than 10 minutes to arrive. |
| p728 | t=183.0s | v1191. | Vehicle took longer than 10 minutes to arrive. |
| p737 | t=185.0s | v1056. | Vehicle took longer than 10 minutes to arrive. |
| p740 | t=188.0s | v640. | Vehicle took longer than 10 minutes to arrive. |
| p752 | t=189.0s | v1283. | Vehicle took longer than 10 minutes to arrive. |
| p753 | t=189.0s | v1283. | Vehicle took longer than 10 minutes to arrive. |
| p754 | t=189.0s | v2978. | Vehicle took longer than 10 minutes to arrive. |
| p759 | t=191.0s | v2647. | Vehicle took longer than 10 minutes to arrive. |
| p768 | t=195.0s | v1314. | Vehicle took longer than 10 minutes to arrive. |
| p787 | t=199.0s | v1373. | Vehicle took longer than 10 minutes to arrive. |
| p800 | t=203.0s | v640. | Vehicle took longer than 10 minutes to arrive. |
| p804 | t=203.0s | v448. | Vehicle took longer than 10 minutes to arrive. |
| p809 | t=203.0s | v2537. | Vehicle took longer than 10 minutes to arrive. |
| p813 | t=205.0s | v2337. | Vehicle took longer than 10 minutes to arrive. |
| p814 | t=205.0s | v2337. | Vehicle took longer than 10 minutes to arrive. |
| p815 | t=205.0s | v1440. | Vehicle took longer than 10 minutes to arrive. |
| p823 | t=208.0s | v2759. | Vehicle took longer than 10 minutes to arrive. |
| p838 | t=211.0s | v1823. | Vehicle took longer than 10 minutes to arrive. |
| p857 | t=215.0s | v1224. | Vehicle took longer than 10 minutes to arrive. |
| p870 | t=217.0s | v1191. | Vehicle took longer than 10 minutes to arrive. |
| p874 | t=219.0s | v959. | Vehicle took longer than 10 minutes to arrive. |
| p875 | t=219.0s | v959. | Vehicle took longer than 10 minutes to arrive. |
| p896 | t=222.0s | v1226. | Vehicle took longer than 10 minutes to arrive. |
| p897 | t=222.0s | v1226. | Vehicle took longer than 10 minutes to arrive. |
| p921 | t=226.0s | v409. | Vehicle took longer than 10 minutes to arrive. |
