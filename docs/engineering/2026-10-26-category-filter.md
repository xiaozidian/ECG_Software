# Workstation category selection and waveform review

The four heartbeat filters select the complete category when switching categories. Activating the already selected category opens its subtype menu. Switching resets the previous subtype, template filter, edit selection and linked cohort. The other-category aggregate includes existing beat records outside N/S/V; it does not relabel beats or infer diagnoses.

The workstation keeps full-width vertical twelve-lead review, recorder-clock ticks, sample-rate/stride information, and device-unit amplitude boundaries. Voltage remains uncalibrated. Compact screens scroll rather than distorting waveforms. Representative strips use their own sample geometry.

Validation for category selection: 13 mathematical browser interaction checks and 42 focused category, density and cache checks passed. Mathematical test inputs are generated locally. No patient source data, identity fields, screenshots, runtime databases or waveform exports are included in this commit. This engineering validation does not establish clinical performance or hospital calibration equivalence.

The existing local read caches and lossless HRV response compression are retained. Native report generation and browser mathematical demos remain separate paths. No deployment or clinical approval is claimed here.
