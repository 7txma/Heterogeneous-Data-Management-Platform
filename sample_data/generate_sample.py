"""Generate a messy multi-table Excel sample for demo queries."""

from pathlib import Path

import pandas as pd

out = Path(__file__).resolve().parent / "messy_emissions.xlsx"

with pd.ExcelWriter(out, engine="openpyxl") as writer:
    # Sheet 1: two vertical blocks separated by empty rows
    block1 = pd.DataFrame(
        [
            ["US State Emissions Summary", "", "", ""],
            ["State", "Year", "NOx_emissions_kt", "Data_source"],
            ["Alaska", 2020, 42.7, "EPA NEI"],
            ["California", 2020, 512.3, "EPA NEI"],
            ["Texas", 2020, 698.1, "EPA NEI"],
        ]
    )
    block1.to_excel(writer, sheet_name="State_Summary", index=False, header=False, startrow=0)

    block2 = pd.DataFrame(
        [
            ["Sector detail (Alaska)", "", ""],
            ["Sector", "Year", "NOx_emissions_kt"],
            ["Transportation", 2020, 18.2],
            ["Industry", 2020, 12.5],
        ]
    )
    block2.to_excel(writer, sheet_name="State_Summary", index=False, header=False, startrow=8)

    # Sheet 2: hierarchical-style headers
    hier = pd.DataFrame(
        [
            ["Region", "Year", "Air Pollutant", "Air Pollutant", "Notes"],
            ["", "", "NOx", "SO2", ""],
            ["Alaska", 2019, 44.1, 11.2, "state total"],
            ["Alaska", 2020, 42.7, 10.8, "state total"],
            ["California", 2020, 512.3, 98.4, "state total"],
        ]
    )
    hier.to_excel(writer, sheet_name="MultiHeader", index=False, header=False)

print(f"Wrote {out}")
