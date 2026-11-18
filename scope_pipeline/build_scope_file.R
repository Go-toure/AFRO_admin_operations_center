# ============================================================
# BUILD SCOPE FILE
#
# Merges the two GPEI inputs -- the preparedness-dashboard export
# ("lookup.xlsx") and the Calendar "Download Scopes" export
# ("gpei_scopes.csv") -- into the final scope_.csv used downstream.
#
# This is your existing scope-building logic, unchanged. The only edits
# vs. what you had were the three hardcoded file paths (the two inputs
# and the one output), which now point at this project's own data/
# folder instead of the old "Mes documents" location, via base_dir below
# (override with the GPEI_SCOPE_HOME environment variable if needed, same
# as scripts/download_gpei_scopes.py).
#
# Run standalone with:  Rscript scripts/build_scope_file.R
# Or let scripts/download_gpei_scopes.py call this automatically right
# after it fetches fresh lookup.xlsx / gpei_scopes.csv files.
# ============================================================

library(tidyverse)
library(dplyr)
library(sf)
library(flextable)
library(stringr)
library(stringi)
library(lubridate)
library(readxl)

get_script_dir <- function() {
  args <- commandArgs(trailingOnly = FALSE)
  file_arg <- "--file="
  match <- grep(file_arg, args)
  if (length(match) > 0) {
    return(dirname(normalizePath(sub(file_arg, "", args[match]))))
  }
  return(getwd())
}
base_dir <- Sys.getenv("GPEI_SCOPE_HOME", unset = dirname(get_script_dir()))

# lqas <- read_csv("C:/Users/TOURE/Mes documents/REPOSITORIES/LQAS_raw_data/AFRO_LQAS_data_c.csv")
polioutbrk <- read_excel(file.path(base_dir, "data", "lookup.xlsx"))
calendar <- read_csv(file.path(base_dir, "data", "gpei_scopes.csv"))
polioutbrk$Country[polioutbrk$Country == "CÔTE D’IVOIRE"] <- "COTE D IVOIRE"
Polioutbrk<-polioutbrk |>
  rename(roundn = `Round Number`,
         response = `OBR Name`,
         vaccine.type = Vaccines,
         country = Country,
         # Renamed away from round_start_date (was `Round Start Date`) --
         # `calend` below now carries its own round_start_date straight
         # from gpei_scopes.csv's own "Start date" column, so this no
         # longer needs to share that name. See the FIX comment on
         # calend's own rename() below for why.
         lookup_round_start_date = `Round Start Date`) |>
  mutate(roundNumber = case_when(
    roundn =="Round 0"~ "Rnd0",
    roundn =="Round 1"~ "Rnd1",
    roundn =="Round 2"~ "Rnd2",
    roundn =="Round 3"~ "Rnd3",
    roundn =="Round 4"~ "Rnd4",
    roundn =="Round 5"~ "Rnd5",
    roundn =="Round 6"~ "Rnd6")) |>
  dplyr::select(country, response, roundNumber, vaccine.type, lookup_round_start_date)
calend<-calendar |>
  rename(rndn = `Round Number`,
         response = `OBR Name`,
         country = `Admin 0`,
         province = `Admin 1`,
         district = `Admin 2`,
         vaccine.type = Vaccine,
         # FIX: gpei_scopes.csv already carries each round's own start
         # date (added when the GPEI fetch moved from the Calendar UI
         # export to the REST API) -- use it directly instead of relying
         # on the country+response+roundNumber merge with lookup.xlsx
         # below to attach one. That merge can silently fail to match a
         # country's rows because the two GPEI API fields the country
         # names come from -- the campaign's top-level org unit (used for
         # lookup.xlsx) vs. a district's grandparent org unit (used for
         # gpei_scopes.csv) -- don't always spell that country identically
         # (accents, spacing, casing). A failed match left round_start_date
         # NA, and the `filter(month != "NA")` step further down then
         # silently dropped every one of that country's rows for the whole
         # period -- even though its district-level scope data had been
         # fetched correctly. Sourcing the date from calend's own column
         # removes that dependency entirely.
         round_start_date = `Start date`) |>
  mutate(roundNumber = case_when(
    rndn =="R0"~ "Rnd0",
    rndn =="R1"~ "Rnd1",
    rndn =="R2"~ "Rnd2",
    rndn =="R3"~ "Rnd3",
    rndn =="R4"~ "Rnd4",
    rndn =="R5"~ "Rnd5",
    rndn =="R6"~ "Rnd6"))  |>
  dplyr::select(country, province, district, response, vaccine.type, roundNumber, round_start_date) |>
  filter(vaccine.type !="NA", response!="NIE-2023-10-01_bOPV")
calend$country[calend$country == "CÔTE D’IVOIRE"] <- "COTE D IVOIRE"
# Left join (all.x = TRUE) -- kept so Polioutbrk/lookup.xlsx's columns
# (e.g. lookup_round_start_date, unused below) stay available on
# Calendare for reference/debugging, but it can no longer silently drop
# or blank out any of calend's own rows: round_start_date (and every
# other column actually selected further down) now comes from calend
# itself, not from this join, so a country-name mismatch between the two
# input files no longer loses that country's data.
Calendare <- merge(x=calend, y=Polioutbrk,
                   by=c("country" = "country",
                        "response" = "response",
                        "roundNumber" = "roundNumber"),
                   all.x = TRUE) |>
  mutate(round_start_date = as_date(round_start_date)) |>
  mutate(month_yr = format(as.Date(round_start_date), "%Y-%m")) |>
  mutate(
    province = case_when(
      province == "SIKASSO" & response =="MAI-2024-02-01_nOPV" & round_start_date == "2024-09-27"~ "KAYES",
      TRUE~ province)) |>
  mutate( district = case_when(
    district =="SELINGUE" & response =="MAI-2024-02-01_nOPV" & round_start_date == "2024-09-27"~ "KENIEBA",
    district =="YANFOLILA" & response =="MAI-2024-02-01_nOPV" & round_start_date == "2024-09-27"~ "SAGABARI",
    TRUE~ district)) |>
  mutate(response = case_when(
    response =="MAI-2024-02-01_nOPV" & round_start_date == "2024-09-27"~ "Small-scale SIA-2Ds",
    TRUE~ response)) |>
  mutate(round_start_date = case_when(
    response =="MAI-2024-02-01_nOPV" & round_start_date == "2024-09-27"~ as_date("2024-09-06"),
    response =="GHA-2024-10-01_nOPV" & roundNumber == "Rnd1"~ as_date("2024-10-17"),
    response =="DRC-sNID-09-2024_bOPV" & roundNumber == "Rnd1"~ as_date("2024-09-19"),
    response =="DRC-sNID-01-2024-bOPV" & roundNumber == "Rnd1"~ as_date("2024-02-02"),
    response =="DRC-NID-03-2024-nOPV" & roundNumber == "Rnd1"~ as_date("2024-03-28"),
    response =="CIV-2024-04-01_nOPV" & roundNumber == "Rnd1"~ as_date("2024-05-10"),
    response =="CIV-2024-04-01_nOPV" & roundNumber == "Rnd2"~ as_date("2024-09-06"),
    TRUE~ round_start_date)) |>
  dplyr::select(country, province, district, response, vaccine.type = vaccine.type.x, roundNumber, round_start_date) |>
  mutate(round_start_date = as_date(round_start_date)) |>
  filter(response !="ZIM-2024-01-01_nOPV",
         response != "ANGOLA-NID2-2024-nOPV2",
         response != "ANG-2024-05-01_bOPV",
         response != "TNZ-2024-01-01_nOPV",
         response != "SLE-2024-09-NID_nOPV",
         response != "NIE-2024-02-01_bOPV",
         response != "DRC-NID-05-2024-nOPV",
         response != "CIV-2024-09-NIDs_nOPV",
         response != "CNG-2024-02-nOPV",
         response != "TEST")
c<-Calendare |>
  mutate(month = month(round_start_date)) |>
  filter(month != "NA") |>
  arrange(month)|>
  mutate(district = toupper(district)) |>
  mutate(district = case_when(
    country	=="ANGOLA"&	district	=="AMBUÃLA" ~	"AMBUILA",
    country	=="ANGOLA"&	district	=="BAÃA FARTA" ~	"BAIA FARTA",
    country	=="ANGOLA"&	district	=="LÃ‰UA" ~	"LEUA",
    country	=="ANGOLA"&	district	=="LÃ“VUA" ~	"LOVUA",
    country	=="ANGOLA"&	district	=="BUENGAS (EX. NOVA ESPERANÃ‡A)" ~	"BUENGAS",
    country	=="ANGOLA"&	district	=="CAÃLA" ~	"CAALA",
    country	=="ANGOLA"&	district	=="CACONGO (EX. LÃ‚NDANA)" ~	"CACONGO",
    country	=="ANGOLA"&	district	=="SAMBA CAJÃš" ~	"SAMBA CAJU",
    country	=="ANGOLA"&	district	=="TÃ”MBUA (EX. PORTO ALEXANDRE)" ~	"TOMBUA",
    country	=="ANGOLA"&	district	=="UÃGE" ~	"UIGE",
    country	=="ANGOLA"&	district	=="NÃ“QUI" ~	"NOQUI",
    country	=="ANGOLA"&	district	=="N'HARÃŠA" ~	"NHAREA",
    country	=="ANGOLA"&	district	=="XÃ-MUTEBA" ~	"XA MUTEBA",
    country	=="ANGOLA"&	district	=="N'HARÃŠA" ~	"NHAREA",
    country	=="ANGOLA"&	district	=="NGONGUEMBO" ~	"GONGUEMBO",
    country	=="ANGOLA"&	district	=="NÃ“QUI" ~	"NOQUI",
    country	=="ANGOLA"&	district	=="PANGO-ALUQUEM" ~	"PANGO ALUQUEM",
    country	=="ANGOLA"&	district	=="TÃ”MBUA (EX. PORTO ALEXANDRE)" ~	"TOMBUA",
    country	=="ANGOLA"&	district	=="UCUMA" ~	"UKUMA",
    country	=="ANGOLA"&	district	=="UÃGE" ~	"UIGE",
    country	=="ANGOLA"&	district	=="XÃ-MUTEBA" ~	"XA MUTEBA",
    country	=="ANGOLA"&	district	=="NZETU" ~	"NZETO",
    country	=="ANGOLA"&	district	=="CELA (EX. UACU-CUNGO)" ~	"CELA",
    country	=="ANGOLA"&	district	=="OMBADJA (EX. CUAMATO)" ~	"OMBADJA",
    country	=="ANGOLA"&	district	=="TCHICALA TCHOLOHANGA" ~	"TCHIKALA-TCHOLOHAN",
    country	=="ANGOLA"&	district	=="BUNDAS" ~	"LUMBALA NGUIMBO (BUNDAS)",
    country	=="ANGOLA"&	district	=="AMBOIM (EX. GABELA)" ~	"AMBOIM",
    country	=="ANGOLA"&	district	=="AMBUÃLA" ~	"AMBUILA",
    country	=="ANGOLA"&	district	=="BAÃA FARTA" ~	"BAIA FARTA",
    country	=="ANGOLA"&	district	=="BUENGAS (EX. NOVA ESPERANÃ‡A)" ~	"BUENGAS",
    country	=="ANGOLA"&	district	=="BULA-ATUMBA" ~	"BULA ATUMBA",
    country	=="ANGOLA"&	district	=="QUIUABA-N'ZOGI" ~	"KIWABA NZOGI",
    country	=="ANGOLA"&	district	=="SAMBA CAJÃš" ~	"SAMBA CAJU",
    country	=="ANGOLA"&	district	=="SELES (EX. UCU SELES)" ~	"SELES",
    country	=="ANGOLA"&	district	=="SUMBE (EX. NGUNZA)" ~	"SUMBE",
    country	=="ANGOLA"&	district	=="CAMEIA" ~	"LUMEJE (CAMEIA)",
    country	=="ANGOLA"&	district	=="CATABOLA (EX. NOVA SINTRA)" ~	"CATABOLA",
    country	=="ANGOLA"&	district	=="LÃ‰UA" ~	"LEUA",
    country	=="ANGOLA"&	district	=="LIBOLO (EX. CALULO)" ~	"LIBOLO",
    country	=="ANGOLA"&	district	=="LÃ“VUA" ~	"LOVUA",
    country	=="ANGOLA"&	district	=="BUNDAS-LUMBALA-NGUIMBO" ~	"LUMBALA NGUIMBO (BUNDAS)",
    country	=="ANGOLA"&	district	=="CAÃLA" ~	"CAALA",
    country	=="ANGOLA"&	district	=="CACONGO (EX. LÃ‚NDANA)" ~	"CACONGO",
    country	=="ANGOLA"&	district	=="DANDE (CAXITO)" ~	"DANDE",
    country	=="ANGOLA"&	district	=="DEMBOS-QUIBAXE" ~	"DEMBOS (QUIBAXE)",
    country	=="ANGOLA"&	district	=="GAMBOS (EX. CHIANGE)" ~	"GAMBOS",
    country	=="ANGOLA"&	district	=="CUNDA-DIA-BAZE" ~	"KUNDA-DIA-BAZE",
    country	=="ANGOLA"&	district	=="CUNHINGA (VOUGA)" ~	"CUNHINGA",
    country	=="ANGOLA"&	district	=="MUCABA (EX. QUINZALA)" ~	"MUCABA",
    country	=="ANGOLA"&	district	=="MUCARI" ~	"CACULAMA (MUCARI)",
    country	=="ANGOLA"&	district	=="TCHIKALA TCHOLOHANG" ~	"TCHIKALA-TCHOLOHAN",
    country	=="ANGOLA"&	district	=="CUROCA (EX. ONCOCUA)" ~	"CUROCA",
    country	=="ANGOLA"&	district	=="MILUNGA (SANTA CRUZ)" ~	"MILUNGA",
    country	=="ANGOLA"&	district	=="LUENA" ~	"MOXICO (LUENA)",
    country == "ANGOLA" & district == "TCHIKALA TCHOLOHANG" ~ "TCHIKALA TCHOLOHANGA",
    country == "ANGOLA" & district == "NGOLA KILUANGE" ~ "NGOLA QUILUANGE",
    country == "ANGOLA" & district == "CACULAMA" ~ "CACULAMA (MUCARI)",
    country == "ANGOLA" & district == "BUNDAS" ~ "BUENGAS",
    country == "ANGOLA" & district == "LUMBALA NGUIMBO" ~ "LUMBALA NGUIMBO (BUNDAS)",
    country	=="NIGER"&	district	=="AGUIÃ‰" ~	"AGUIÉ",
    country	=="NIGE"&	district	=="TCHIROZÃ‰RINE" ~	"TCHIROZÉRINE",
    country	=="NIGER"&	district =="TÃ‰RA" ~	"TERA",
    country	=="NIGER"&	district	=="GOURÃ‰" ~	"GOURÉ",
    country	=="NIGER"&	district	=="IFÃ‰ROUANE" ~	"IFÉROUANE",
    country	=="NIGER"&	district	=="ILLÃ‰LA" ~	"ILLÉLA",
    country	=="NIGER"&	district	=="MATAMÃˆYE" ~	"MATAMEYE",
    country	=="NIGER"&	district	=="FILINGUÃ‰" ~	"FILINGUE",
    country	=="NIGER"&	district	=="KANTCHÃ‰" ~	"KANTCHÉ",
    country	=="NIGER"&	district	=="GOTHÃˆYE" ~	"GOTHÈYE",
    country	=="NIGER"&	district	=="JINJA CITY‰" ~	"JINJA",
    country	=="NIGER"&	district	=="MBALE CITY" ~	"MBALE",
    country	=="MAURITANIA"&	district	=="RIYADH" ~	"RIYAD",
    country	=="MAURITANIA"&	district	=="LEKSEIBE" ~	"LEXEIBA",
    country	=="MAURITANIA"&	district	=="WOMPOU" ~	"WOMPO",
    country	=="MAURITANIA"&	district	=="ADEL BAGHROU" ~	"ADEL BEGROU",
    country	=="MAURITANIA"&	district	=="AKJOUJET" ~	"AKJOUJT",
    country	=="MAURITANIA"&	district	=="BABABE" ~	"BABABÉ",
    country	=="MAURITANIA"&	district	=="BIR OUMGREINE" ~	"BIR MOGHREN",
    country	=="MAURITANIA"&	district	=="BOGHE" ~	"BOGHÉ",
    country	=="MAURITANIA"&	district	=="BARKEOL" ~	"BARKÉOLE",
    country	=="MAURITANIA"&	district	=="CHINGUITTI" ~	"CHINGUITTY",
    country	=="MAURITANIA"&	district	=="D_HAR" ~	"D'HAR",
    country	=="MAURITANIA"&	district	=="BOUTILIMITT" ~	"BOUTILIMIT",
    country	=="MAURITANIA"&	district	=="F_DERIK" ~	"F'DERICK",
    country	=="MAURITANIA"&	district	=="GUERROU" ~	"GUÉRROU",
    country	=="MAURITANIA"&	district	=="KANKOUSSA" ~	"KANKOSSA",
    country	=="MAURITANIA"&	district	=="KOBENNI" ~	"KOBENI",
    country	=="MAURITANIA"&	district	=="M_BAGNE" ~	"M'BAGNE",
    country	=="MAURITANIA"&	district	=="M_BOUT" ~	"M'BOUT",
    country	=="MAURITANIA"&	district	=="MAGHTA LEHJAR" ~	"MAGTA LAHJAR",
    country	=="MAURITANIA"&	district	=="MOUDJRIA" ~	"MOUDJÉRIA",
    country	=="MAURITANIA"&	district	=="NEMA" ~	"NÉMA",
    country	=="MAURITANIA"&	district	=="OUAD-NAGA" ~	"OUAD NAGA",
    country	=="MAURITANIA"&	district	=="R_KIZ" ~	"R'KIZ",
    country	=="MAURITANIA"&	district	=="SEILIBABY" ~	"SELIBABY",
    country	=="MAURITANIA"&	district	=="TAMCHEKETT" ~	"TAMCHAKET",
    country	=="MAURITANIA"&	district	=="TEVRAGH ZEINE" ~	"TEVRAGH ZEINA",
    country	=="MAURITANIA"&	district	=="TICHITT" ~	"TICHIT",
    country	=="MAURITANIA"&	district	=="TIMBEDRA" ~	"TIMBÉDRA",
    country	=="MAURITANIA"&	district	=="ZOUERATE" ~	"ZOUÉRAT",
    country	=="MOZAMBIQUE"&	district	=="CHIÃšRE" ~	"CHIÚRE",
    country	=="MOZAMBIQUE"&	district	=="MARÃVIA" ~	"MARÁVIA",
    country	=="MOZAMBIQUE"&	district	=="MAÃšA" ~	"MAUA",
    country	=="MOZAMBIQUE"&	district	=="ALTO MOLÃ“CUÃˆ" ~	"ALTO MOLOCUE",
    country	=="MOZAMBIQUE"&	district	=="ANGÃ“NIA" ~	"ANGONIA",
    country	=="MOZAMBIQUE"&	district	=="MOCÃMBOA DA PRAIA" ~	"MACIMBOA DA PRAI",
    country	=="MOZAMBIQUE"&	district	=="MÃGOÃˆ" ~	"MÁGOÈ",
    country	=="MOZAMBIQUE"&	district	=="GURUÃ‰" ~	"GURUE",
    country	=="MOZAMBIQUE"&	district	=="GILÃ‰" ~	"GILÉ",
    country	=="MOZAMBIQUE"&	district	=="NGAÃšMA" ~	"NGAÚMA",
    TRUE~district)) |>
  mutate(province = case_when(
    country	=="ANGOLA"&	province	=="UÃGE" &	district	=="AMBUILA" ~	"UIGE",
    country	=="ANGOLA"&	province	=="BIÃ‰" &	district	=="ANDULO" ~	"BIE",
    country	=="ANGOLA"&	province	=="BENGUELA" &	district	=="BAIA FARTA" ~	"BENGUELA",
    country	=="ANGOLA"&	province	=="HUAMBO" &	district	=="TCHIKALA-TCHOLOHAN" ~	"HUAMBO",
    country	=="ANGOLA"&	province	=="MOXICO" &	district	=="ALTO ZAMBEZE" ~	"MOXICO",
    country	=="ANGOLA"&	province	=="CUANZA NORTE" &	district	=="AMBACA" ~	"CUANZA NORTE",
    country	=="ANGOLA"&	province	=="CUANZA SUL" &	district	=="AMBOIM" ~	"KWANZA SUL",
    country	=="ANGOLA"&	province	=="BENGO" &	district	=="AMBRIZ" ~	"BENGO",
    country	=="ANGOLA"&	province	=="BIÃ‰" &	district	=="CUITO" ~	"BIE",
    country	=="ANGOLA"&	province	=="CUANDO CUBANGO" &	district	=="CUITO CUANAVALE" ~	"KUANDO KUBANGO",
    country	=="ANGOLA"&	province	=="MALANJE" &	district	=="KUNDA-DIA-BAZE" ~	"MALANGE",
    country	=="ANGOLA"&	province	=="BIÃ‰" &	district	=="CUNHINGA" ~	"BIE",
    country	=="ANGOLA"&	province	=="CUNENE" &	district	=="CUROCA" ~	"CUNENE",
    country	=="ANGOLA"&	province	=="HUÃLA" &	district	=="CUVANGO" ~	"HUILA",
    country	=="ANGOLA"&	province	=="CUNENE" &	district	=="CUVELAI" ~	"CUNENE",
    country	=="ANGOLA"&	province	=="LUNDA SUL" &	district	=="DALA" ~	"LUNDA SUL",
    country	=="ANGOLA"&	province	=="UÃGE" &	district	=="DAMBA" ~	"UIGE",
    country	=="ANGOLA"&	province	=="BENGO" &	district	=="DANDE" ~	"BENGO",
    country	=="ANGOLA"&	province	=="BENGO" &	district	=="DEMBOS (QUIBAXE)" ~	"BENGO",
    country	=="ANGOLA"&	province	=="CUANDO CUBANGO" &	district	=="DIRICO" ~	"KUANDO KUBANGO",
    country	=="ANGOLA"&	province	=="CUANZA SUL" &	district	=="EBO" ~	"KWANZA SUL",
    country	=="ANGOLA"&	province	=="HUAMBO" &	district	=="ECUNHA" ~	"HUAMBO",
    country	=="ANGOLA"&	province	=="HUÃLA" &	district	=="GAMBOS" ~	"HUILA",
    country	=="ANGOLA"&	province	=="BENGUELA" &	district	=="GANDA" ~	"BENGUELA",
    country	=="ANGOLA"&	province	=="CUANZA NORTE" &	district	=="GOLUNGO ALTO" ~	"KWANZA NORTE",
    country	=="ANGOLA"&	province	=="HUAMBO" &	district	=="HUAMBO" ~	"HUAMBO",
    country	=="ANGOLA"&	province	=="HUÃLA" &	district	=="HUMPATA" ~	"HUILA",
    country	=="ANGOLA"&	province	=="LUANDA" &	district	=="ICOLO E BENGO" ~	"BENGO",
    country	=="ANGOLA"&	province	=="LUANDA" &	district	=="INGOMBOTA" ~	"LUANDA",
    country	=="ANGOLA"&	province	=="HUÃLA" &	district	=="JAMBA" ~	"HUILA",
    country	=="ANGOLA"&	province	=="LUANDA" &	district	=="KILAMBA KIAXI" ~	"LUANDA",
    country	=="ANGOLA"&	province	=="MOXICO" &	district	=="LEUA" ~	"MOXICO",
    country	=="ANGOLA"&	province	=="CUANZA SUL" &	district	=="LIBOLO" ~	"KWANZA SUL",
    country	=="ANGOLA"&	province	=="BENGUELA" &	district	=="LOBITO" ~	"BENGUELA",
    country	=="ANGOLA"&	province	=="HUAMBO" &	district	=="LONDUIMBALE" ~	"HUAMBO",
    country	=="ANGOLA"&	province	=="HUAMBO" &	district	=="LONGONJO" ~	"HUAMBO",
    country	=="ANGOLA"&	province	=="LUNDA NORTE" &	district	=="LOVUA" ~	"LUNDA NORTE",
    country	=="ANGOLA"&	province	=="MOXICO" &	district	=="LUACANO" ~	"MOXICO",
    country	=="ANGOLA"&	province	=="MOXICO" &	district	=="LUAU" ~	"MOXICO",
    country	=="ANGOLA"&	province	=="LUNDA NORTE" &	district	=="LUBALO" ~	"LUNDA NORTE",
    country	=="ANGOLA"&	province	=="HUÃLA" &	district	=="LUBANGO" ~	"HUILA",
    country	=="ANGOLA"&	province	=="CUANZA NORTE" &	district	=="LUCALA" ~	"KWANZA NORTE",
    country	=="ANGOLA"&	province	=="LUNDA NORTE" &	district	=="LUCAPA" ~	"LUNDA NORTE",
    country	=="ANGOLA"&	province	=="MOXICO" &	district	=="LUCHAZES" ~	"MOXICO",
    country	=="ANGOLA"&	province	=="MOXICO" &	district	=="MOXICO (LUENA)" ~	"MOXICO",
    country	=="ANGOLA"&	province	=="MALANJE" &	district	=="LUQUEMBO" ~	"MALANGE",
    country	=="ANGOLA"&	province	=="LUANDA" &	district	=="MAIANGA" ~	"LUANDA",
    country	=="ANGOLA"&	province	=="MALANJE" &	district	=="MALANJE" ~	"MALANJE",
    country	=="ANGOLA"&	province	=="UÃGE" &	district	=="MAQUELA DO ZOMBO" ~	"UIGE",
    country	=="ANGOLA"&	province	=="MALANJE" &	district	=="MARIMBA" ~	"MALANGE",
    country	=="ANGOLA"&	province	=="MALANJE" &	district	=="MASSANGO" ~	"MALANGE",
    country	=="ANGOLA"&	province	=="HUÃLA" &	district	=="MATALA" ~	"HUILA",
    country	=="ANGOLA"&	province	=="CUANDO CUBANGO" &	district	=="MAVINGA" ~	"KUANDO KUBANGO",
    country	=="ANGOLA"&	province	=="ZAIRE" &	district	=="MBANZA CONGO" ~	"ZAIRE",
    country	=="ANGOLA"&	province	=="CUANDO CUBANGO" &	district	=="MENONGUE" ~	"KUANDO KUBANGO",
    country	=="ANGOLA"&	province	=="UÃGE" &	district	=="MILUNGA" ~	"UIGE",
    country	=="ANGOLA"&	province	=="UÃGE" &	district	=="MUCABA" ~	"UIGE",
    country	=="ANGOLA"&	province	=="MALANJE" &	district	=="CACULAMA (MUCARI)" ~	"MALANJE",
    country	=="ANGOLA"&	province	=="LUNDA SUL" &	district	=="MUCONDA" ~	"LUNDA SUL",
    country	=="ANGOLA"&	province	=="MALANJE" &	district	=="CACULAMA (MUCARI)" ~	"MALANJE",
    country	=="ANGOLA"&	province	=="LUANDA" &	district	=="LUANDA" ~	"LUANDA",
    country	=="ANGOLA"&	province	=="CUANZA SUL" &	district	=="MUSSENDE" ~	"CUANZA SUL",
    country	=="ANGOLA"&	province	=="MOXICO" &	district	=="LUMBALA NGUIMBO (BUNDAS)" ~	"MOXICO",
    country	=="ANGOLA"&	province	=="BENGO" &	district	=="NAMBUANGONGO" ~	"BENGO",
    country	=="ANGOLA"&	province	=="MOXICO" &	district	=="LUMBALA NGUIMBO (BUNDAS)" ~	"MOXICO",
    country	=="ANGOLA"&	province	=="CUANDO CUBANGO" &	district	=="NANCOVA" ~	"CUANDO CUBANGO",
    country	=="ANGOLA"&	province	=="HUAMBO" &	district	=="BAILUNDO" ~	"HUAMBO",
    country	=="ANGOLA"&	province	=="BENGUELA" &	district	=="BALOMBO" ~	"BENGUELA",
    country	=="ANGOLA"&	province	=="CUANZA NORTE" &	district	=="BANGA" ~	"KWANZA NORTE",
    country	=="ANGOLA"&	province	=="LUANDA" &	district	=="BELAS" ~	"LUANDA",
    country	=="ANGOLA"&	province	=="CABINDA" &	district	=="BELIZE" ~	"CABINDA",
    country	=="ANGOLA"&	province	=="UÃGE" &	district	=="BEMBE" ~	"UIGE",
    country	=="ANGOLA"&	province	=="BENGUELA" &	district	=="BENGUELA" ~	"BENGUELA",
    country	=="ANGOLA"&	province	=="NAMIBE" &	district	=="BIBALA" ~	"NAMIBE",
    country	=="ANGOLA"&	province	=="BENGUELA" &	district	=="BOCOIO" ~	"BENGUELA",
    country	=="ANGOLA"&	province	=="CUANZA NORTE" &	district	=="BOLONGONGO" ~	"KWANZA NORTE",
    country	=="ANGOLA"&	province	=="CABINDA" &	district	=="BUCO ZAU" ~	"CABINDA",
    country	=="ANGOLA"&	province	=="UÃGE" &	district	=="BUENGAS" ~	"UIGE",
    country	=="ANGOLA"&	province	=="BENGO" &	district	=="BULA ATUMBA" ~	"KWANZA NORTE",
    country	=="ANGOLA"&	province	=="MOXICO" &	district	=="LUMBALA NGUIMBO (BUNDAS)" ~	"MOXICO",
    country	=="ANGOLA"&	province	=="UÃGE" &	district	=="BUNGO" ~	"UIGE",
    country	=="ANGOLA"&	province	=="HUAMBO" &	district	=="CAALA" ~	"HUAMBO",
    country	=="ANGOLA"&	province	=="CABINDA" &	district	=="CABINDA" ~	"CABINDA",
    country	=="ANGOLA"&	province	=="LUNDA SUL" &	district	=="CACOLO" ~	"LUNDA SUL",
    country	=="ANGOLA"&	province	=="HUÃLA" &	district	=="CACONDA" ~	"HUILA",
    country	=="ANGOLA"&	province	=="CABINDA" &	district	=="CACONGO" ~	"CABINDA",
    country	=="ANGOLA"&	province	=="LUANDA" &	district	=="CACUACO" ~	"LUANDA",
    country	=="ANGOLA"&	province	=="HUÃLA" &	district	=="CACULA" ~	"HUILA",
    country	=="ANGOLA"&	province	=="MALANJE" &	district	=="CACUSO" ~	"MALANGE",
    country	=="ANGOLA"&	province	=="CUNENE" &	district	=="CAHAMA" ~	"CUNENE",
    country	=="ANGOLA"&	province	=="MALANJE" &	district	=="CAHOMBO" ~	"MALANGE",
    country	=="ANGOLA"&	province	=="BENGUELA" &	district	=="CAIMBAMBO" ~	"BENGUELA",
    country	=="ANGOLA"&	province	=="CUANDO CUBANGO" &	district	=="CALAI" ~	"KUANDO KUBANGO",
    country	=="ANGOLA"&	province	=="MALANJE" &	district	=="CALANDULA" ~	"MALANGE",
    country	=="ANGOLA"&	province	=="HUÃLA" &	district	=="CALUQUEMBE" ~	"HUILA",
    country	=="ANGOLA"&	province	=="BIÃ‰" &	district	=="CAMACUPA" ~	"BIE",
    country	=="ANGOLA"&	province	=="MOXICO" &	district	=="CAMANONGUE" ~	"MOXICO",
    country	=="ANGOLA"&	province	=="CUANZA NORTE" &	district	=="CAMBAMBE" ~	"CUANZA NORTE",
    country	=="ANGOLA"&	province	=="LUNDA NORTE" &	district	=="CAMBULO" ~	"LUNDA NORTE",
    country	=="ANGOLA"&	province	=="MALANJE" &	district	=="CAMBUNDI CATEMBO" ~	"MALANJE",
    country	=="ANGOLA"&	province	=="MOXICO" &	district	=="LUMEJE (CAMEIA)" ~	"MOXICO",
    country	=="ANGOLA"&	province	=="NAMIBE" &	district	=="CAMUCUIO" ~	"NAMIBE",
    country	=="ANGOLA"&	province	=="MALANJE" &	district	=="CANGANDALA" ~	"MALANGE",
    country	=="ANGOLA"&	province	=="UÃGE" &	district	=="CANGOLA" ~	"UIGE",
    country	=="ANGOLA"&	province	=="LUNDA NORTE" &	district	=="CAPENDA CAMULEMBA" ~	"LUNDA NORTE",
    country	=="ANGOLA"&	province	=="CUANZA SUL" &	district	=="CASSONGUE" ~	"CUANZA SUL",
    country	=="ANGOLA"&	province	=="BIÃ‰" &	district	=="CATABOLA" ~	"BIE",
    country	=="ANGOLA"&	province	=="HUAMBO" &	district	=="CATCHIUNGO" ~	"HUAMBO",
    country	=="ANGOLA"&	province	=="BENGUELA" &	district	=="CATUMBELA" ~	"BENGUELA",
    country	=="ANGOLA"&	province	=="LUNDA NORTE" &	district	=="CAUNGULA" ~	"LUNDA NORTE",
    country	=="ANGOLA"&	province	=="LUANDA" &	district	=="CAZENGA" ~	"LUANDA",
    country	=="ANGOLA"&	province	=="CUANZA NORTE" &	district	=="CAZENGO" ~	"CUANZA NORTE",
    country	=="ANGOLA"&	province	=="CUANZA SUL" &	district	=="CELA" ~	"KWANZA SUL",
    country	=="ANGOLA"&	province	=="HUÃLA" &	district	=="CHIBIA" ~	"HUILA",
    country	=="ANGOLA"&	province	=="HUÃLA" &	district	=="CHICOMBA" ~	"HUILA",
    country	=="ANGOLA"&	province	=="BIÃ‰" &	district	=="CHINGUAR" ~	"BIE",
    country	=="ANGOLA"&	province	=="HUÃLA" &	district	=="CHIPINDO" ~	"HUILA",
    country	=="ANGOLA"&	province	=="LUNDA NORTE" &	district	=="CHITATO" ~	"LUNDA NORTE",
    country	=="ANGOLA"&	province	=="BIÃ‰" &	district	=="CHITEMBO" ~	"BIE",
    country	=="ANGOLA"&	province	=="BENGUELA" &	district	=="CHONGOROI" ~	"BENGUELA",
    country	=="ANGOLA"&	province	=="CUANZA SUL" &	district	=="CONDA" ~	"KWANZA SUL",
    country	=="ANGOLA"&	province	=="CUANDO CUBANGO" &	district	=="CUANGAR" ~	"KUANDO KUBANGO",
    country	=="ANGOLA"&	province	=="LUNDA NORTE" &	district	=="CUANGO" ~	"LUNDA NORTE",
    country	=="ANGOLA"&	province	=="CUNENE" &	district	=="CUANHAMA" ~	"CUNENE",
    country	=="ANGOLA"&	province	=="BENGUELA" &	district	=="CUBAL" ~	"BENGUELA",
    country	=="ANGOLA"&	province	=="CUANDO CUBANGO" &	district	=="CUCHI" ~	"KUANDO KUBANGO",
    country	=="ANGOLA"&	province	=="BIÃ‰" &	district	=="CUEMBA" ~	"BIE",
    country	=="ANGOLA"&	province	=="LUNDA NORTE" &	district	=="CUILO" ~	"LUNDA NORTE",
    country	=="ANGOLA"&	province	=="ZAIRE" &	district	=="CUIMBA" ~	"ZAIRE",
    country	=="ANGOLA"&	province	=="CUANDO CUBANGO" &	district	=="RIVUNGO" ~	"KUANDO KUBANGO",
    country	=="ANGOLA"&	province	=="LUANDA" &	district	=="SAMBA" ~	"LUANDA",
    country	=="ANGOLA"&	province	=="CUANZA NORTE" &	district	=="SAMBA CAJU" ~	"KWANZA NORTE",
    country	=="ANGOLA"&	province	=="LUANDA" &	district	=="SAMBIZANGA" ~	"LUANDA",
    country	=="ANGOLA"&	province	=="UÃGE" &	district	=="SANZA POMBO" ~	"UIGE",
    country	=="ANGOLA"&	province	=="LUNDA SUL" &	district	=="SAURIMO" ~	"LUNDA SUL",
    country	=="ANGOLA"&	province	=="CUANZA SUL" &	district	=="SELES" ~	"KWANZA SUL",
    country	=="ANGOLA"&	province	=="ZAIRE" &	district	=="SOYO" ~	"ZAIRE",
    country	=="ANGOLA"&	province	=="UÃGE" &	district	=="SONGO" ~	"UIGE",
    country	=="ANGOLA"&	province	=="CUANZA SUL" &	district	=="SUMBE" ~	"KWANZA SUL",
    country	=="ANGOLA"&	province	=="LUANDA" &	district	=="TALATONA" ~	"LUANDA",
    country	=="ANGOLA"&	province	=="HUAMBO" &	district	=="TCHIKALA-TCHOLOHAN" ~	"HUAMBO",
    country	=="ANGOLA"&	province	=="HUAMBO" &	district	=="TCHINJENJE" ~	"HUAMBO",
    country	=="ANGOLA"&	province	=="ZAIRE" &	district	=="TOMBOCO" ~	"ZAIRE",
    country	=="ANGOLA"&	province	=="NAMIBE" &	district	=="TOMBUA" ~	"NAMIBE",
    country	=="ANGOLA"&	province	=="HUAMBO" &	district	=="UKUMA" ~	"HUAMBO",
    country	=="ANGOLA"&	province	=="UÃGE" &	district	=="UIGE" ~	"UIGE",
    country	=="ANGOLA"&	province	=="LUANDA" &	district	=="VIANA" ~	"LUANDA",
    country	=="ANGOLA"&	province	=="UÃGE" &	district	=="NEGAGE" ~	"UIGE",
    country	=="ANGOLA"&	province	=="LUANDA" &	district	=="NEVES BENDINHA" ~	"LUANDA",
    country	=="ANGOLA"&	province	=="LUANDA" &	district	=="NGOLA QUILUANGE" ~	"LUANDA",
    country	=="ANGOLA"&	province	=="CUANZA NORTE" &	district	=="GONGUEMBO" ~	"KWANZA NORTE",
    country	=="ANGOLA"&	province	=="ZAIRE" &	district	=="NOQUI" ~	"ZAIRE",
    country	=="ANGOLA"&	province	=="ZAIRE" &	district	=="NZETO" ~	"ZAIRE",
    country	=="ANGOLA"&	province	=="CUNENE" &	district	=="OMBADJA" ~	"CUNENE",
    country	=="ANGOLA"&	province	=="BENGO" &	district	=="PANGO ALUQUEM" ~	"KWANZA NORTE",
    country	=="ANGOLA"&	province	=="CUANZA SUL" &	district	=="PORTO AMBOIM" ~	"KWANZA SUL",
    country	=="ANGOLA"&	province	=="UÃGE" &	district	=="PURI" ~	"UIGE",
    country	=="ANGOLA"&	province	=="MALANJE" &	district	=="QUELA" ~	"MALANJE",
    country	=="ANGOLA"&	province	=="CUANZA SUL" &	district	=="QUIBALA" ~	"CUANZA SUL",
    country	=="ANGOLA"&	province	=="CUANZA NORTE" &	district	=="QUICULUNGO" ~	"CUANZA NORTE",
    country	=="ANGOLA"&	province	=="CUANZA SUL" &	district	=="QUILENDA" ~	"CUANZA SUL",
    country	=="ANGOLA"&	province	=="HUÃLA" &	district	=="QUILENGUES" ~	"HUILA",
    country	=="ANGOLA"&	province	=="UÃGE" &	district	=="QUIMBELE" ~	"UIGE",
    country	=="ANGOLA"&	province	=="HUÃLA" &	district	=="QUIPUNGO" ~	"HUILA",
    country	=="ANGOLA"&	province	=="MALANJE" &	district	=="QUIRIMA" ~	"MALANGE",
    country	=="ANGOLA"&	province	=="LUANDA" &	district	=="QUISSAMA" ~	"LUANDA",
    country	=="ANGOLA"&	province	=="UÃGE" &	district	=="QUITEXE" ~	"UIGE",
    country	=="ANGOLA"&	province	=="MALANJE" &	district	=="KIWABA NZOGI" ~	"MALANGE",
    country	=="ANGOLA"&	province	=="LUANDA" &	district	=="RANGEL" ~	"LUANDA",
    country	=="ANGOLA"&	province	=="BIÃ‰" &	district	=="NHAREA" ~	"BIE",
    country	=="ANGOLA"&	province	=="NAMIBE" &	district	=="VIREI" ~	"NAMIBE",
    country	=="ANGOLA"&	province	=="LUNDA NORTE" &	district	=="XA MUTEBA" ~	"LUNDA NORTE",
    country	=="ANGOLA"&	province	=="HUAMBO" &	district	=="MUNGO" ~	"HUAMBO",
    country	=="ANGOLA"&	province	=="CUNENE" &	district	=="NAMACUNDE" ~	"CUNENE",
    country	=="ANGOLA"&	province	=="NAMIBE" &	district	=="NAMIBE" ~	"NAMIBE",
    TRUE~ province))
c$rnd_distinct <- paste(c$response, c$roundNumber, sep = "_")

# ---- AFROGDB name standardization (added 16 Nov 2026) --------------------------------------
# Adds geo_code, geo_match, std_country, std_province, std_district. The names in country /
# province / district are NOT changed, so no existing join breaks. Matching rules are the ones
# in AFRO-Geo-Reference (R/afrogdb_standardize.R): exact, normalized, other province, reviewed
# crosswalk, then the extended layers of crosswalk_extended.csv (manual decisions, Ethiopia woreda to zone, relaxed, old
# shape, name similarity; geo_match says which, "(probable)" for the last two). A name that is not found keeps geo_code = NA and is listed (counts only) in
# logs/scope_unmatched_names.csv. If AFRO-Geo-Reference cannot be found the build goes on without
# the columns (set AFRO_GEO_REFERENCE_DIR to its folder).
geo_ref_dir <- Sys.getenv("AFRO_GEO_REFERENCE_DIR", unset = file.path(dirname(base_dir), "AFRO-Geo-Reference"))
std_script <- file.path(geo_ref_dir, "R", "afrogdb_standardize.R")
if (file.exists(std_script)) {
  tryCatch({
    source(std_script)
    geo_ref <- afrogdb_reference(geo_ref_dir)
    std <- afrogdb_standardize(as.data.frame(c), "country", "province", "district", ref = geo_ref, replace_names = TRUE, verbose = TRUE, extended = TRUE)
    c$geo_code     <- std$geo_code
    c$geo_match    <- std$geo_match
    c$std_country  <- std$country
    c$std_province <- std$province
    c$std_district <- std$district
    un <- attr(std, "unmatched")
    dir.create(file.path(base_dir, "logs"), showWarnings = FALSE)
    write_csv(as.data.frame(un), file.path(base_dir, "logs", "scope_unmatched_names.csv"))
    cat("SCOPE: AFROGDB geo_code added; ", nrow(un), " unit name(s) not found (logs/scope_unmatched_names.csv)\n", sep = "")
  }, error = function(e) cat("SCOPE: AFROGDB standardization skipped (", conditionMessage(e), ")\n", sep = ""))
} else {
  cat("SCOPE: AFRO-Geo-Reference not found at ", geo_ref_dir, "; geo_code columns not added\n", sep = "")
}

write_csv(c, file.path(base_dir, "data", "scope_.csv"))
