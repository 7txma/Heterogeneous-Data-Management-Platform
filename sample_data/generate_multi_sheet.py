import pandas as pd
from pathlib import Path

out = Path(__file__).resolve().parent / "multi_sheet_emissions.xlsx"

readme = pd.DataFrame(
    [
        ["Updated March 25, 2021"],
        [
            "This workbook contains state-level CAP emissions trends. "
            "Highway data for 2018 through 2020 were updated using NOx & SO2 CAMD emissions."
        ],
        ["Updated April 27, 2020"],
        ["Updates since May 30, 2019 include revised sector mapping and documentation notes."],
    ]
)

state = pd.DataFrame(
    [
        ["Emissions in thousands of tons", None, None, None, None, None, None],
        [
            "State FIPS",
            "State",
            "Sector",
            "Pollutant",
            "Pollutant Description",
            "emissions2002",
            "emissions2004",
        ],
        ["02", "AK", "Transportation", "NOX", "Nitrogen Oxides", 20.1, 18.5],
        ["02", "AK", "Industry", "NOX", "Nitrogen Oxides", 22.6, 24.0],
        ["06", "CA", "Transportation", "NOX", "Nitrogen Oxides", 400.0, 380.0],
    ]
)

trends = pd.DataFrame(
    [
        ["State", "Pollutant", "Year", "Emissions"],
        ["AK", "NOX", 2002, 42.7],
        ["AK", "NOX", 2004, 42.5],
        ["CA", "NOX", 2004, 512.3],
    ]
)

with pd.ExcelWriter(out, engine="openpyxl") as writer:
    readme.to_excel(writer, sheet_name="README", index=False, header=False)
    state.to_excel(writer, sheet_name="State_Trends", index=False, header=False)
    trends.to_excel(writer, sheet_name="DevelopmentOfData", index=False, header=False)

print(f"Wrote {out}")
