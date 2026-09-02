# AzNFS validation status

90 distro release(s) across 847 marketplace SKU(s).

**Known supported:** 8 | **Known unsupported:** 28 | **Unknown / not yet validated:** 54

_Generated automatically from the validation database by the AzNFS pipeline; the commit date shows when it was last refreshed. Do not edit by hand._

## Known supported (8)

| Distro | Latest image version | Publishers | SKUs |
| --- | --- | --- | ---: |
| Debian 12 | 0.20260824.2580 | Debian | 2 |
| Debian 13 | 0.20260902.2589 | Debian | 4 |
| Rocky 8 | 8.9.20231119 | resf | 1 |
| Rocky 9 | 9.8.20260525 | resf | 1 |
| Ubuntu 20.04 | 20.04.202505230 | Canonical | 2 |
| Ubuntu 22.04 | 22.04.202608310 | Canonical | 2 |
| Ubuntu 24.04 | 24.04.202607280 | Canonical | 2 |
| Ubuntu 26.04 | 26.04.202609010 | Canonical | 6 |

## Known unsupported (28)

| Distro | Latest image version | Publishers | SKUs | Reason |
| --- | --- | --- | ---: | --- |
| Azure Linux 3 | 3.20260809.01 | MicrosoftCBLMariner | 2 | prod repo is missing |
| CBL-Mariner 2 | 2.20260331.01 | MicrosoftCBLMariner | 2 | prod repo is missing |
| Debian | 0.20260831.2587 | Debian | 3 | prod repo is missing |
| Debian 10 | 0.20240703.1797 | Debian | 1 | repo is found but packages are not found because distro is not supported by AzNFS |
| Debian 11 | 0.20260901.2588 | Debian | 5 | repo is found but packages are not found because distro is not supported by AzNFS |
| Debian 14 | 0.20260901.2588 | Debian | 3 | prod repo is missing |
| RHEL 7 | 7.9.2026031104 | RedHat | 1 | no AzNFS packages found on prod and packages.csv does not require modification; publish packages manually and re-invoke Phase 2 |
| RHEL 7.9 | 7.9.2026010609 | RedHat | 1 | no AzNFS packages found on prod and packages.csv does not require modification; publish packages manually and re-invoke Phase 2 |
| RHEL 8 | 8.9.2024021412 | RedHat | 1 | no AzNFS packages found on prod and packages.csv does not require modification; publish packages manually and re-invoke Phase 2 |
| RHEL 8.1 | 8.1.2023062611 | RedHat | 1 | no AzNFS packages found on prod and packages.csv does not require modification; publish packages manually and re-invoke Phase 2 |
| RHEL 8.2 | 8.2.2023062611 | RedHat | 1 | no AzNFS packages found on prod and packages.csv does not require modification; publish packages manually and re-invoke Phase 2 |
| RHEL 8.6 | 8.6.2026072112 | RedHat | 1 | prod repo is missing |
| Rocky 10 | 10.2.20260625 | resf | 4 | repo is found but packages are not found because distro is not supported by AzNFS |
| Rocky 8 | 8.10.20260709 | resf | 1 | verify_aznfs_install_lifecycle (lisa_0_0): deployment failed. HttpResponseError: (AuthorizationFailed) The client '<id redacted>' with object id '<id redacted>' does not have authorization to perform action 'Microsoft.MarketplaceOrdering/offerTypes/publishers/offers/plans/agreements/write' over scope '<scope redacted>' or the scope is invalid. If access was recently granted, please refresh your credentials.; verify_aznfs_nfs_functional (lisa_0_1): deployment failed. HttpResponseError: (AuthorizationFailed) The client '<id redacted>' with object id '<id redacted>' does not have authorization to perform action 'Microsoft.MarketplaceOrdering/offerTypes/publishers/offers/plans/agreements/write' over scope '<scope redacted>' or the scope is invalid. If access was recently granted, please refresh your credentials.; verify_aznfs_resilience (lisa_0_2): deployment failed. HttpResponseError: (AuthorizationFailed) The client '<id redacted>' with object id '<id redacted>' does not have authorization to perform action 'Microsoft.MarketplaceOrdering/offerTypes/publishers/offers/plans/agreements/write' over scope '<scope redacted>' or the scope is invalid. If access was recently granted, please refresh your credentials. |
| Rocky 9 | 9.8.20260525 | resf | 1 | no AzNFS packages found on prod and packages.csv does not require modification; publish packages manually and re-invoke Phase 2 |
| SLES 12 | 2026.06.29 | SUSE | 1 | repo is found but packages are not found because distro is not supported by AzNFS |
| SUSE Linux | 2026.09.01 | SUSE | 9 | prod repo is missing |
| Ubuntu 14.04 | 14.04.20200601 | Canonical | 1 | repo is found but packages are not found because distro is not supported by AzNFS |
| Ubuntu 16.04 | 16.04.202512150 | Canonical | 1 | prod repo is missing |
| Ubuntu 18.04 | 18.04.202607310 | Canonical | 1 | no AzNFS packages found on prod and packages.csv does not require modification; publish packages manually and re-invoke Phase 2 |
| Ubuntu 22.04 | 22.04.202608210 | Canonical | 2 | no AzNFS packages found on prod and packages.csv does not require modification; publish packages manually and re-invoke Phase 2; verify_aznfs_install_lifecycle (lisa_0_0): failed. AssertionError: [Failed to uninstall ['aznfs'], please check the package name and repo are correct or not. |
| Ubuntu 24.04 | 24.04.202608270 | Canonical | 1 | prod repo is missing |
| Ubuntu 25.04 | 25.04.202601140 | Canonical | 2 | repo is found but packages are not found because distro is not supported by AzNFS |
| Ubuntu 25.10 | 25.10.202607040 | Canonical | 2 | repo is found but packages are not found because distro is not supported by AzNFS |
| Ubuntu 26.04 | 26.04.202608310 | Canonical | 2 | prod repo is missing |
| Ubuntu 26.10 | 26.10.202608220 | Canonical | 2 | prod repo is missing |
| Ubuntu Core 24 | 24.04.202512030 | Canonical | 1 | prod repo is missing |
| openSUSE | 2026.02.05 | SUSE | 2 | prod repo is missing |

## Unknown / not yet validated (54)

| Distro | Latest image version | Publishers | SKUs |
| --- | --- | --- | ---: |
| Azure Linux 3 | 3.20260809.01 | MicrosoftCBLMariner | 12 |
| CBL-Mariner 2 | 2.20260331.01 | MicrosoftCBLMariner | 4 |
| Debian 10 | 0.20240703.1797 | Debian | 3 |
| Debian 11 | 0.20260805.2561 | Debian | 5 |
| Debian 12 | 0.20260824.2580 | Debian | 10 |
| Debian 13 | 0.20260902.2589 | Debian | 8 |
| RHEL | 9.8.2026080415 | RedHat | 119 |
| RHEL 10 | 10.2.2026080415 | RedHat | 9 |
| RHEL 10.0 | 10.0.2026081908 | RedHat | 16 |
| RHEL 10.1 | 10.1.2026051512 | RedHat | 6 |
| RHEL 10.2 | 10.2.2026080415 | RedHat | 14 |
| RHEL 7 | 7.9.2026031104 | RedHat | 3 |
| RHEL 7.6 | 7.6.2021062302 | RedHat | 4 |
| RHEL 7.7 | 7.7.2021062302 | RedHat | 2 |
| RHEL 7.9 | 7.9.2026010609 | RedHat | 5 |
| RHEL 8 | 8.9.2024022012 | RedHat | 3 |
| RHEL 8.0 | 8.0.2022031402 | RedHat | 2 |
| RHEL 8.1 | 8.1.2023062611 | RedHat | 3 |
| RHEL 8.10 | 8.10.2026081238 | RedHat | 13 |
| RHEL 8.2 | 8.2.2023062611 | RedHat | 3 |
| RHEL 8.3 | 8.3.2022031401 | RedHat | 4 |
| RHEL 8.4 | 8.4.2025031317 | RedHat | 10 |
| RHEL 8.5 | 8.5.2023092113 | RedHat | 2 |
| RHEL 8.6 | 8.6.2026060213 | RedHat | 11 |
| RHEL 8.7 | 8.7.2023112914 | RedHat | 5 |
| RHEL 8.8 | 8.8.2026031104 | RedHat | 11 |
| RHEL 8.9 | 8.9.2024040517 | RedHat | 4 |
| RHEL 9 | 9.8.2026080415 | RedHat | 7 |
| RHEL 9.0 | 9.0.2026050606 | RedHat | 9 |
| RHEL 9.1 | 9.1.2023092113 | RedHat | 3 |
| RHEL 9.2 | 9.2.2026082118 | RedHat | 13 |
| RHEL 9.3 | 9.3.2024043014 | RedHat | 3 |
| RHEL 9.4 | 9.4.2026082409 | RedHat | 12 |
| RHEL 9.5 | 9.5.2025052607 | RedHat | 6 |
| RHEL 9.6 | 9.6.2026081810 | RedHat | 14 |
| RHEL 9.7 | 9.7.2026051512 | RedHat | 6 |
| RHEL 9.8 | 9.8.2026080415 | RedHat | 14 |
| Rocky 8 | 8.9.20231119 | resf | 2 |
| Rocky 9 | 9.8.20260525 | resf | 2 |
| SLES 12 | 2026.06.29 | SUSE | 7 |
| SLES 15 | 2026.08.27 | SUSE | 65 |
| SLES 16 | 2026.08.05 | SUSE | 18 |
| SUSE Linux | 2026.08.26 | SUSE | 105 |
| Ubuntu 14.04 | 14.04.20200601 | Canonical | 1 |
| Ubuntu 16.04 | 16.04.202512150 | Canonical | 9 |
| Ubuntu 18.04 | 18.04.202608280 | Canonical | 21 |
| Ubuntu 20.04 | 20.04.202608300 | Canonical | 29 |
| Ubuntu 22.04 | 22.04.202608310 | Canonical | 55 |
| Ubuntu 24.04 | 24.04.202608290 | Canonical | 27 |
| Ubuntu 25.04 | 25.04.202601140 | Canonical | 7 |
| Ubuntu 25.10 | 25.10.202607040 | Canonical | 10 |
| Ubuntu 26.04 | 26.04.202609010 | Canonical | 31 |
| Ubuntu 26.10 | 26.10.202608220 | Canonical | 4 |
| openSUSE | 2026.02.05 | SUSE | 1 |
