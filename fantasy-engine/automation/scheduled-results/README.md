# Scheduled Results

Output from the `Fantasy Football Weekly Schedule` GitHub Actions workflow
(`.github/workflows/fantasy-weekly-schedule.yml`), one subfolder per weekday
routine:

| Day       | Routine            | CLI command                          |
|-----------|---------------------|---------------------------------------|
| monday    | trading             | `workflow --task trade_analysis`      |
| tuesday   | waivers             | `tuesday`                             |
| wednesday | additional analysis | `workflow --task additional_analysis` |
| thursday  | lineup              | `thursday`                            |
| saturday  | lineup              | `sunday` (final check before Sunday games) |

Each run adds a dated file (`<day>-<label>-YYYY-MM-DD.json`) and overwrites
`latest.json` in that day's folder, so `scheduled-results/monday/latest.json`
always holds the most recent trade analysis, and so on.
