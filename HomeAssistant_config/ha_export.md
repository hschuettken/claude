# Home Assistant Data Export

> **Generated**: 2026-02-11 08:49 UTC  
> **HA Version**: 2025.10.2  
> **Instance**: Home  
> **Location**: 52.318012142152504, 7.785098254680634 (Europe/Berlin)

## Summary

- **7** areas
- **80** devices
- **942** entities across **31** domains
- **280** services across **68** domains

## Areas

| Area | Entities |
|------|----------|
| Bedroom | 0 |
| Kitchen | 0 |
| Küche | 2 |
| Living Room | 1 |
| Office | 5 |
| guest_WC | 3 |
| mechanical | 124 |

## Entities by Domain

- [sensor](#sensor) (562)
- [binary_sensor](#binary_sensor) (99)
- [light](#light) (31)
- [switch](#switch) (61)
- [climate](#climate) (13)
- [cover](#cover) (14)
- [media_player](#media_player) (3)
- [camera](#camera) (2)
- [vacuum](#vacuum) (1)
- [automation](#automation) (9)
- [script](#script) (4)
- [scene](#scene) (7)
- [input_boolean](#input_boolean) (18)
- [input_number](#input_number) (5)
- [input_select](#input_select) (1)
- [input_datetime](#input_datetime) (1)
- [number](#number) (35)
- [select](#select) (12)
- [button](#button) (6)
- [device_tracker](#device_tracker) (9)
- [person](#person) (2)
- [zone](#zone) (5)
- [sun](#sun) (1)
- [weather](#weather) (4)
- [update](#update) (25)
- [calendar](#calendar) (2)
- [conversation](#conversation) (1)
- [event](#event) (3)
- [remote](#remote) (1)
- [siren](#siren) (2)
- [time](#time) (3)

### sensor

562 entities

| Entity ID | Name | State | Unit | Class | Area |
|-----------|------|-------|------|-------|------|
| `sensor.hp_officejet_8010_series` | HP OfficeJet 8010 series | idle |  | enum | Office |
| `sensor.hp_officejet_8010_series_black_cartridge` | HP OfficeJet 8010 series black cartridge | 80 | % |  | Office |
| `sensor.hp_officejet_8010_series_cyan_cartridge` | HP OfficeJet 8010 series cyan cartridge | 60 | % |  | Office |
| `sensor.hp_officejet_8010_series_magenta_cartridge` | HP OfficeJet 8010 series magenta cartridge | 70 | % |  | Office |
| `sensor.hp_officejet_8010_series_yellow_cartridge` | HP OfficeJet 8010 series yellow cartridge | 60 | % |  | Office |
| `sensor.gaestewc_esp32_guest_wc_humidity` | gaesteWC-esp32 Guest WC Humidity | unavailable | % | humidity | guest_WC |
| `sensor.gaestewc_esp32_guest_wc_temperature` | gaesteWC-esp32 Guest WC Temperature | unavailable | °C | temperature | guest_WC |
| `sensor.batteries_bus_current` | Batteries Bus current | 0.0 | A | current | mechanical |
| `sensor.batteries_bus_voltage` | Batteries Bus voltage | 748.4 | V | voltage | mechanical |
| `sensor.batteries_capacity_control_periods` | Batteries Capacity control periods | 0 |  |  | mechanical |
| `sensor.batteries_charge_discharge_power` | Batteries Charge/Discharge power | 0 | W | power | mechanical |
| `sensor.batteries_day_charge` | Batteries Day charge | 0.01 | kWh | energy | mechanical |
| `sensor.batteries_day_discharge` | Batteries Day discharge | 2.43 | kWh | energy | mechanical |
| `sensor.batteries_forcible_charge` | Batteries Forcible Charge | Stopped |  |  | mechanical |
| `sensor.batteries_maximum_charge_power` | Batteries Maximum charge power | 3500 | W | power | mechanical |
| `sensor.batteries_maximum_discharge_power` | Batteries Maximum discharge power | 3500 | W | power | mechanical |
| `sensor.batteries_rated_capacity` | Batteries Rated Capacity | 6900 | Wh |  | mechanical |
| `sensor.batteries_state_of_capacity` | Batteries State of capacity | 5.0 | % |  | mechanical |
| `sensor.batteries_status` | Batteries Status | Running |  |  | mechanical |
| `sensor.batteries_total_charge` | Batteries Total charge | 954.14 | kWh | energy | mechanical |
| `sensor.batteries_total_discharge` | Batteries Total discharge | 930.25 | kWh | energy | mechanical |
| `sensor.batteries_tou_charging_and_discharging_periods` | Batteries TOU charging and discharging periods | 2 |  |  | mechanical |
| `sensor.battery_1_bms_temperature` | Battery_1 BMS temperature | 24.9 | °C | temperature | mechanical |
| `sensor.battery_1_running_status` | Battery_1 Running status | Running |  |  | mechanical |
| `sensor.battery_1_soh_calibration_status` | Battery_1 SOH calibration status | 0 |  |  | mechanical |
| `sensor.battery_1_state_of_capacity` | Battery_1 State of capacity | 5.0 | % |  | mechanical |
| `sensor.battery_1_working_mode` | Battery_1 Working mode | Maximise self consumption |  |  | mechanical |
| `sensor.heatdistreg_esp32_heatdistreg_rueckfluss_temp_badeg` | heatdistreg-esp32 heatdistreg_rueckfluss_temp_badeg | 16.375 | °C | temperature | mechanical |
| `sensor.heatdistreg_esp32_heatdistreg_rueckfluss_temp_esszimmer_fenster` | heatdistreg-esp32 heatdistreg_rueckfluss_temp_esszimmer_fenster | 19.25 | °C | temperature | mechanical |
| `sensor.heatdistreg_esp32_heatdistreg_rueckfluss_temp_esszimmer_kueche` | heatdistreg-esp32 heatdistreg_rueckfluss_temp_esszimmer_kueche | 19.5625 | °C | temperature | mechanical |
| `sensor.heatdistreg_esp32_heatdistreg_rueckfluss_temp_flur_eg` | heatdistreg-esp32 heatdistreg_rueckfluss_temp_flur_eg | 18.4375 | °C | temperature | mechanical |
| `sensor.heatdistreg_esp32_heatdistreg_rueckfluss_temp_kueche` | heatdistreg-esp32 heatdistreg_rueckfluss_temp_kueche | 19.5625 | °C | temperature | mechanical |
| `sensor.heatdistreg_esp32_heatdistreg_rueckfluss_temp_sport` | heatdistreg-esp32 heatdistreg_rueckfluss_temp_sport | 17.1875 | °C | temperature | mechanical |
| `sensor.heatdistreg_esp32_heatdistreg_rueckfluss_temp_wozi_kamin` | heatdistreg-esp32 heatdistreg_rueckfluss_temp_wozi_kamin | 20.9375 | °C | temperature | mechanical |
| `sensor.heatdistreg_esp32_heatdistreg_rueckfluss_temp_wozi_sportwand` | heatdistreg-esp32 heatdistreg_rueckfluss_temp_wozi_sportwand | 19.875 | °C | temperature | mechanical |
| `sensor.heatdistreg_esp32_heatdistreg_rueckfluss_temperatur_geastebad` | heatdistreg-esp32 heatdistreg_rueckfluss_temperatur_geastebad | 16.5625 | °C | temperature | mechanical |
| `sensor.inverter_active_power` | Inverter Active power | 415 | W | power | mechanical |
| `sensor.inverter_active_power_control` | Inverter Active power control | Unlimited |  |  | mechanical |
| `sensor.inverter_alarms` | Inverter Alarms | None |  |  | mechanical |
| `sensor.inverter_current_electricity_generation_statistics_time` | Inverter Current electricity generation statistics time | 2026-02-11T07:47:08+00:00 |  | timestamp | mechanical |
| `sensor.inverter_daily_yield` | Inverter Daily yield | 2.51 | kWh | energy | mechanical |
| `sensor.inverter_day_active_power_peak` | Inverter Day active power peak | 3428 | W | power | mechanical |
| `sensor.inverter_device_status` | Inverter Device status | On-grid |  |  | mechanical |
| `sensor.inverter_dsp_data_collection` | Inverter DSP data collection | DSP data collection |  |  | mechanical |
| `sensor.inverter_efficiency` | Inverter Efficiency | 100.0 | % |  | mechanical |
| `sensor.inverter_hourly_yield` | Inverter Hourly yield | 0.24 | kWh | energy | mechanical |
| `sensor.inverter_input_power` | Inverter Input power | 415 | W | power | mechanical |
| `sensor.inverter_internal_temperature` | Inverter Internal temperature | 43.2 | °C | temperature | mechanical |
| `sensor.inverter_inverter_state` | Inverter Inverter state | Grid-Connected, Grid-Connected normally |  |  | mechanical |
| `sensor.inverter_locking_status` | Inverter Locking status | Locked |  |  | mechanical |
| `sensor.inverter_max_active_power` | Inverter Max active power | 22000 | W | power | mechanical |
| `sensor.inverter_off_grid_status` | Inverter Off-grid status | On-grid |  |  | mechanical |
| `sensor.inverter_off_grid_switch` | Inverter Off-grid switch | Off-grid switch disabled |  |  | mechanical |
| `sensor.inverter_power_factor` | Inverter Power factor | 0.885 |  | power_factor | mechanical |
| `sensor.inverter_pv_1_current` | Inverter PV 1 current | 0.39 | A | current | mechanical |
| `sensor.inverter_pv_1_voltage` | Inverter PV 1 voltage | 397.8 | V | voltage | mechanical |
| `sensor.inverter_pv_2_current` | Inverter PV 2 current | 0.29 | A | current | mechanical |
| `sensor.inverter_pv_2_voltage` | Inverter PV 2 voltage | 397.8 | V | voltage | mechanical |
| `sensor.inverter_pv_3_current` | Inverter PV 3 current | 0.33 | A | current | mechanical |
| `sensor.inverter_pv_3_voltage` | Inverter PV 3 voltage | 418.6 | V | voltage | mechanical |
| `sensor.inverter_pv_4_current` | Inverter PV 4 current | 0.33 | A | current | mechanical |
| `sensor.inverter_pv_4_voltage` | Inverter PV 4 voltage | 418.6 | V | voltage | mechanical |
| `sensor.inverter_pv_connection_status` | Inverter PV connection status | PV connected |  |  | mechanical |
| `sensor.inverter_rated_power` | Inverter Rated power | 20000 | W | power | mechanical |
| `sensor.inverter_reactive_power` | Inverter Reactive power | 218 | var | reactive_power | mechanical |
| `sensor.inverter_shutdown_time` | Inverter Shutdown time | unknown |  | timestamp | mechanical |
| `sensor.inverter_startup_time` | Inverter Startup time | 2026-02-11T06:15:46+00:00 |  | timestamp | mechanical |
| `sensor.inverter_total_dc_input_energy` | Inverter Total DC input energy | 3373.8 | kWh | energy | mechanical |
| `sensor.inverter_total_yield` | Inverter Total yield | 2923.78 | kWh | energy | mechanical |
| `sensor.knx_interface_connection_established` | KNX Interface Connection established | 2026-02-08T14:58:14+00:00 |  | timestamp | mechanical |
| `sensor.knx_interface_connection_type` | KNX Interface Connection type | Tunnel TCP |  | enum | mechanical |
| `sensor.knx_interface_incoming_telegram_errors` | KNX Interface Incoming telegram errors | 0 | errors |  | mechanical |
| `sensor.knx_interface_individual_address` | KNX Interface Individual address | 1.1.6 |  |  | mechanical |
| `sensor.knx_interface_outgoing_telegram_errors` | KNX Interface Outgoing telegram errors | 0 | errors |  | mechanical |
| `sensor.knx_interface_telegrams` | KNX Interface Telegrams | 106338 | telegrams |  | mechanical |
| `sensor.power_meter_active_power` | Power meter Active power | -118 | W | power | mechanical |
| `sensor.power_meter_consumption` | Power meter Consumption | 2046.75 | kWh | energy | mechanical |
| `sensor.power_meter_exported` | Power meter Exported | 1205.05 | kWh | energy | mechanical |
| `sensor.power_meter_frequency` | Power meter Frequency | 50.0 | Hz | frequency | mechanical |
| `sensor.power_meter_meter_status` | Power meter Meter status | Normal |  |  | mechanical |
| `sensor.power_meter_phase_a_active_power` | Power meter Phase A active power | 122 | W | power | mechanical |
| `sensor.power_meter_phase_a_current` | Power meter Phase A current | 0.95 | A | current | mechanical |
| `sensor.power_meter_phase_a_voltage` | Power meter Phase A voltage | 226.3 | V | voltage | mechanical |
| `sensor.power_meter_phase_b_active_power` | Power meter Phase B active power | -211 | W | power | mechanical |
| `sensor.power_meter_phase_b_current` | Power meter Phase B current | -1.29 | A | current | mechanical |
| `sensor.power_meter_phase_b_voltage` | Power meter Phase B voltage | 224.6 | V | voltage | mechanical |
| `sensor.power_meter_phase_c_active_power` | Power meter Phase C active power | -29 | W | power | mechanical |
| `sensor.power_meter_phase_c_current` | Power meter Phase C current | -1.31 | A | current | mechanical |
| `sensor.power_meter_phase_c_voltage` | Power meter Phase C voltage | 224.6 | V | voltage | mechanical |
| `sensor.power_meter_power_factor` | Power meter Power factor | 0.112 |  | power_factor | mechanical |
| `sensor.power_meter_reactive_energy` | Power meter Reactive energy | 840.12 | kVarh |  | mechanical |
| `sensor.power_meter_reactive_power` | Power meter Reactive power | -916 | var | reactive_power | mechanical |
| `sensor.shelly3em_main_channel_a_current` | shelly3em_main Phase A Current | 1.7 | A | current | mechanical |
| `sensor.shelly3em_main_channel_a_energy` | shelly3em_main Phase A Energy | 3895.8992 | kWh | energy | mechanical |
| `sensor.shelly3em_main_channel_a_energy_returned` | shelly3em_main Phase A Energy returned | 107.5025 | kWh | energy | mechanical |
| `sensor.shelly3em_main_channel_a_power` | shelly3em_main Phase A Power | 349.36 | W | power | mechanical |
| `sensor.shelly3em_main_channel_a_power_factor` | shelly3em_main Phase A Power factor | 92.0 | % | power_factor | mechanical |
| `sensor.shelly3em_main_channel_a_voltage` | shelly3em_main Phase A Voltage | 225.78 | V | voltage | mechanical |
| `sensor.shelly3em_main_channel_b_current` | shelly3em_main Phase B Current | 0.4 | A | current | mechanical |
| `sensor.shelly3em_main_channel_b_energy` | shelly3em_main Phase B Energy | 3373.5788 | kWh | energy | mechanical |
| `sensor.shelly3em_main_channel_b_energy_returned` | shelly3em_main Phase B Energy returned | 27.0817 | kWh | energy | mechanical |
| `sensor.shelly3em_main_channel_b_power` | shelly3em_main Phase B Power | 12.83 | W | power | mechanical |
| `sensor.shelly3em_main_channel_b_power_factor` | shelly3em_main Phase B Power factor | 14.0 | % | power_factor | mechanical |
| `sensor.shelly3em_main_channel_b_voltage` | shelly3em_main Phase B Voltage | 227.77 | V | voltage | mechanical |
| `sensor.shelly3em_main_channel_c_current` | shelly3em_main Phase C Current | 1.31 | A | current | mechanical |
| `sensor.shelly3em_main_channel_c_energy` | shelly3em_main Phase C Energy | 2770.0788 | kWh | energy | mechanical |
| `sensor.shelly3em_main_channel_c_energy_returned` | shelly3em_main Phase C Energy returned | 46.4402 | kWh | energy | mechanical |
| `sensor.shelly3em_main_channel_c_power` | shelly3em_main Phase C Power | 164.08 | W | power | mechanical |
| `sensor.shelly3em_main_channel_c_power_factor` | shelly3em_main Phase C Power factor | 56.0 | % | power_factor | mechanical |
| `sensor.shelly3em_main_channel_c_voltage` | shelly3em_main Phase C Voltage | 226.05 | V | voltage | mechanical |
| `sensor.amtron_availability_raw` | Amtron Availability (raw) | 1 |  |  |  |
| `sensor.amtron_availability_tpl` | Amtron Availability | Available |  |  |  |
| `sensor.amtron_charge_end_time_hi_raw` | Amtron Charge End Time (HI raw) | 7 |  |  |  |
| `sensor.amtron_charge_end_time_lo_raw` | Amtron Charge End Time (LO raw) | 5462 |  |  |  |
| `sensor.amtron_charge_end_time_tpl` | Amtron Charge End Time | 07:15:56 |  |  |  |
| `sensor.amtron_charge_start_time_hi_raw` | Amtron Charge Start Time (HI raw) | 35 |  |  |  |
| `sensor.amtron_charge_start_time_lo_raw` | Amtron Charge Start Time (LO raw) | 18217 |  |  |  |
| `sensor.amtron_charge_start_time_tpl` | Amtron Charge Start Time | 23:47:29 |  |  |  |
| `sensor.amtron_charged_duration_hh_mm_ss_tpl` | Amtron Charged Duration | 07:28:27 |  |  |  |
| `sensor.amtron_charged_duration_s` | Amtron Charged Duration [s] | 26907 | s |  |  |
| `sensor.amtron_charged_duration_s_tpl` | Amtron Charged Duration [s] (tpl) | unavailable | s |  |  |
| `sensor.amtron_charged_energy_session_kwh` | Amtron Charged Energy Session [kWh] | 48.090 | kWh | energy |  |
| `sensor.amtron_charged_energy_session_kwh_tpl` | Amtron Charged Energy Session [kWh] (tpl) | unavailable | kWh | energy |  |
| `sensor.amtron_communication_timeout_s` | Amtron Communication Timeout [s] | 360 | s |  |  |
| `sensor.amtron_communication_timeout_s_tpl` | Amtron Communication Timeout [s] (tpl) | unavailable | s |  |  |
| `sensor.amtron_device_id` | Amtron Device ID | AM4Y |  |  |  |
| `sensor.amtron_device_id_tpl` | Amtron Device ID (tpl) | unavailable |  |  |  |
| `sensor.amtron_device_name` | Amtron Device Name | Amtron                           |  |  |  |
| `sensor.amtron_device_name_tpl` | Amtron Device Name (tpl) | unavailable |  |  |  |
| `sensor.amtron_error_codes_1_raw_uint32` | Amtron Error Codes 1 (raw uint32) | 0 |  |  |  |
| `sensor.amtron_error_codes_2_raw_uint32` | Amtron Error Codes 2 (raw uint32) | 0 |  |  |  |
| `sensor.amtron_error_codes_3_raw_uint32` | Amtron Error Codes 3 (raw uint32) | 0 |  |  |  |
| `sensor.amtron_error_codes_4_raw_uint32` | Amtron Error Codes 4 (raw uint32) | 0 |  |  |  |
| `sensor.amtron_firmware_version_full_tpl` | Amtron Firmware Version (full) | 1.5.21-0 |  |  |  |
| `sensor.amtron_firmware_version_short` | Amtron Firmware Version (short) | 1.5  |  |  |  |
| `sensor.amtron_firmware_version_short_tpl` | Amtron Firmware Version (short) (tpl) | unavailable |  |  |  |
| `sensor.amtron_fw_build` | Amtron FW Build | 0 |  |  |  |
| `sensor.amtron_fw_build_tpl` | Amtron FW Build (tpl) | unavailable |  |  |  |
| `sensor.amtron_fw_major` | Amtron FW Major | 1 |  |  |  |
| `sensor.amtron_fw_major_tpl` | Amtron FW Major (tpl) | unavailable |  |  |  |
| `sensor.amtron_fw_minor` | Amtron FW Minor | 5 |  |  |  |
| `sensor.amtron_fw_minor_tpl` | Amtron FW Minor (tpl) | unavailable |  |  |  |
| `sensor.amtron_fw_patch` | Amtron FW Patch | 21 |  |  |  |
| `sensor.amtron_fw_patch_tpl` | Amtron FW Patch (tpl) | unavailable |  |  |  |
| `sensor.amtron_hems_current_limit_0_1a_a` | Amtron HEMS Current Limit 0.1A [A] | 16.0 | A | current |  |
| `sensor.amtron_hems_current_limit_0_1a_a_tpl` | Amtron HEMS Current Limit 0.1A [A] (tpl) | unavailable | A | current |  |
| `sensor.amtron_hems_current_limit_a` | Amtron HEMS Current Limit [A] | 16 | A | current |  |
| `sensor.amtron_hems_current_limit_a_tpl` | Amtron HEMS Current Limit [A] (tpl) | unavailable | A | current |  |
| `sensor.amtron_hems_power_limit_w` | Amtron HEMS Power Limit [W] | 0 | W | power |  |
| `sensor.amtron_hems_power_limit_w_tpl` | Amtron HEMS Power Limit [W] (tpl) | unavailable | W | power |  |
| `sensor.amtron_max_charge_current_a` | Amtron Max Charge Current [A] | 16 | A | current |  |
| `sensor.amtron_max_charge_current_a_tpl` | Amtron Max Charge Current [A] (tpl) | unavailable | A | current |  |
| `sensor.amtron_meter_l1_current_a` | Amtron Meter L1 Current [A] | 0.000 | A | current |  |
| `sensor.amtron_meter_l1_current_a_tpl` | Amtron Meter L1 Current [A] (tpl) | unavailable | A | current |  |
| `sensor.amtron_meter_l1_energy_kwh` | Amtron Meter L1 Energy [kWh] | 1936.031 | kWh | energy |  |
| `sensor.amtron_meter_l1_energy_kwh_tpl` | Amtron Meter L1 Energy [kWh] (tpl) | unavailable | kWh | energy |  |
| `sensor.amtron_meter_l1_power_w` | Amtron Meter L1 Power [W] | 0 | W | power |  |
| `sensor.amtron_meter_l1_power_w_tpl` | Amtron Meter L1 Power [W] (tpl) | unavailable | W | power |  |
| `sensor.amtron_meter_l1_voltage_v` | Amtron Meter L1 Voltage [V] | 226 | V | voltage |  |
| `sensor.amtron_meter_l1_voltage_v_tpl` | Amtron Meter L1 Voltage [V] (tpl) | unavailable | V | voltage |  |
| `sensor.amtron_meter_l2_current_a` | Amtron Meter L2 Current [A] | 0.000 | A | current |  |
| `sensor.amtron_meter_l2_current_a_tpl` | Amtron Meter L2 Current [A] (tpl) | unavailable | A | current |  |
| `sensor.amtron_meter_l2_energy_kwh` | Amtron Meter L2 Energy [kWh] | 0.000 | kWh | energy |  |
| `sensor.amtron_meter_l2_energy_kwh_tpl` | Amtron Meter L2 Energy [kWh] (tpl) | unavailable | kWh | energy |  |
| `sensor.amtron_meter_l2_power_w` | Amtron Meter L2 Power [W] | 0 | W | power |  |
| `sensor.amtron_meter_l2_power_w_tpl` | Amtron Meter L2 Power [W] (tpl) | unavailable | W | power |  |
| `sensor.amtron_meter_l2_voltage_v` | Amtron Meter L2 Voltage [V] | 224 | V | voltage |  |
| `sensor.amtron_meter_l2_voltage_v_tpl` | Amtron Meter L2 Voltage [V] (tpl) | unavailable | V | voltage |  |
| `sensor.amtron_meter_l3_current_a` | Amtron Meter L3 Current [A] | 0.000 | A | current |  |
| `sensor.amtron_meter_l3_current_a_tpl` | Amtron Meter L3 Current [A] (tpl) | unavailable | A | current |  |
| `sensor.amtron_meter_l3_energy_kwh` | Amtron Meter L3 Energy [kWh] | 0.000 | kWh | energy |  |
| `sensor.amtron_meter_l3_energy_kwh_tpl` | Amtron Meter L3 Energy [kWh] (tpl) | unavailable | kWh | energy |  |
| `sensor.amtron_meter_l3_power_w` | Amtron Meter L3 Power [W] | 0 | W | power |  |
| `sensor.amtron_meter_l3_power_w_tpl` | Amtron Meter L3 Power [W] (tpl) | unavailable | W | power |  |
| `sensor.amtron_meter_l3_voltage_v` | Amtron Meter L3 Voltage [V] | 224 | V | voltage |  |
| `sensor.amtron_meter_l3_voltage_v_tpl` | Amtron Meter L3 Voltage [V] (tpl) | unavailable | V | voltage |  |
| `sensor.amtron_meter_total_energy_kwh` | Amtron Meter Total Energy [kWh] | 1936.031 | kWh | energy |  |
| `sensor.amtron_meter_total_energy_kwh_tpl` | Amtron Meter Total Energy [kWh] (tpl) | unavailable | kWh | energy |  |
| `sensor.amtron_meter_total_power_w` | Amtron Meter Total Power [W] | 0 | W | power |  |
| `sensor.amtron_meter_total_power_w_tpl` | Amtron Meter Total Power [W] (tpl) | unavailable | W | power |  |
| `sensor.amtron_min_charge_current_a` | Amtron Min Charge Current [A] | 0 | A | current |  |
| `sensor.amtron_min_charge_current_a_tpl` | Amtron Min Charge Current [A] (tpl) | unavailable | A | current |  |
| `sensor.amtron_model` | Amtron Model | 4You 560 11 C2       |  |  |  |
| `sensor.amtron_model_tpl` | Amtron Model (tpl) | unavailable |  |  |  |
| `sensor.amtron_ocpp_cp_status_raw` | Amtron OCPP CP Status (raw) | 1 |  |  |  |
| `sensor.amtron_ocpp_cp_status_raw_tpl` | Amtron OCPP CP Status (raw) (tpl) | unavailable |  |  |  |
| `sensor.amtron_operator_current_limit_a` | Amtron Operator Current Limit [A] | 16 | A | current |  |
| `sensor.amtron_operator_current_limit_a_tpl` | Amtron Operator Current Limit [A] (tpl) | unavailable | A | current |  |
| `sensor.amtron_plug_lock_status_raw` | Amtron Plug Lock Status (raw) | 0 |  |  |  |
| `sensor.amtron_plug_lock_tpl` | Amtron Plug Lock | Unlocked |  |  |  |
| `sensor.amtron_protocol_version` | Amtron Protocol Version | 1.5  |  |  |  |
| `sensor.amtron_protocol_version_tpl` | Amtron Protocol Version (tpl) | unavailable |  |  |  |
| `sensor.amtron_relay_state_raw` | Amtron Relay State (raw) | 0 |  |  |  |
| `sensor.amtron_relay_state_tpl` | Amtron Relay State | Off |  |  |  |
| `sensor.amtron_safe_current_a` | Amtron Safe Current [A] | 6 | A | current |  |
| `sensor.amtron_safe_current_a_tpl` | Amtron Safe Current [A] (tpl) | unavailable | A | current |  |
| `sensor.amtron_signaled_current_to_ev_a` | Amtron Signaled Current to EV [A] | 0 | A | current |  |
| `sensor.amtron_signaled_current_to_ev_a_tpl` | Amtron Signaled Current to EV [A] (tpl) | unavailable | A | current |  |
| `sensor.amtron_vehicle_state_raw` | Amtron Vehicle State (raw) | 1 |  |  |  |
| `sensor.amtron_vehicle_state_tpl` | Amtron Vehicle State | A - No vehicle |  |  |  |
| `sensor.audi_a6_avant_e_tron_car_type` | Audi A6 Avant e-tron Car Type | electric |  |  |  |
| `sensor.audi_a6_avant_e_tron_charging_mode` | Audi A6 Avant e-tron Charging mode | manual |  |  |  |
| `sensor.audi_a6_avant_e_tron_charging_power` | Audi A6 Avant e-tron Charging power | 0.0 | kW | power |  |
| `sensor.audi_a6_avant_e_tron_charging_state` | Audi A6 Avant e-tron Charging state | readyForCharging |  |  |  |
| `sensor.audi_a6_avant_e_tron_charging_type` | Audi A6 Avant e-tron Charging type | ac |  |  |  |
| `sensor.audi_a6_avant_e_tron_climatisation_state` | Audi A6 Avant e-tron Climatisation state | off |  |  |  |
| `sensor.audi_a6_avant_e_tron_doors_trunk_state` | Audi A6 Avant e-tron Doors/trunk state | unknown |  |  |  |
| `sensor.audi_a6_avant_e_tron_external_power` | Audi A6 Avant e-tron External Power | Ready |  |  |  |
| `sensor.audi_a6_avant_e_tron_hybrid_range` | Audi A6 Avant e-tron hybrid Range | 75 | km | distance |  |
| `sensor.audi_a6_avant_e_tron_mileage` | Audi A6 Avant e-tron Mileage | unknown | km | distance |  |
| `sensor.audi_a6_avant_e_tron_plug_led_color` | Audi A6 Avant e-tron Plug LED Color | green |  |  |  |
| `sensor.audi_a6_avant_e_tron_primary_engine_percent` | Audi A6 Avant e-tron Primary engine Percent | 23 | % |  |  |
| `sensor.audi_a6_avant_e_tron_primary_engine_range` | Audi A6 Avant e-tron Primary engine range | 75 | km | distance |  |
| `sensor.audi_a6_avant_e_tron_primary_engine_type` | Audi A6 Avant e-tron Primary engine type | electric |  |  |  |
| `sensor.audi_a6_avant_e_tron_range` | Audi A6 Avant e-tron Range | unknown | km | distance |  |
| `sensor.audi_a6_avant_e_tron_remaining_charge_time` | Audi A6 Avant e-tron Remaining charge time | 0 | min |  |  |
| `sensor.audi_a6_avant_e_tron_remaining_climatisation_time` | Audi A6 Avant e-tron Remaining Climatisation Time | 0 | min |  |  |
| `sensor.audi_a6_avant_e_tron_service_inspection_time` | Audi A6 Avant e-tron Service inspection time | unknown | d |  |  |
| `sensor.audi_a6_avant_e_tron_state_of_charge` | Audi A6 Avant e-tron State of charge | 80 | % | battery |  |
| `sensor.audi_a6_avant_e_tron_target_state_of_charge` | Audi A6 Avant e-tron Target State of charge | 80 | % |  |  |
| `sensor.backup_backup_manager_state` | Backup Backup Manager state | idle |  | enum |  |
| `sensor.backup_last_attempted_automatic_backup` | Backup Last attempted automatic backup | unknown |  | timestamp |  |
| `sensor.backup_last_successful_automatic_backup` | Backup Last successful automatic backup | unknown |  | timestamp |  |
| `sensor.backup_next_scheduled_automatic_backup` | Backup Next scheduled automatic backup | unknown |  | timestamp |  |
| `sensor.bad_eg_diagnosetext` | Bad EG Diagnosetext | Wi H Frost   0 |  |  |  |
| `sensor.bad_og_heizen_ventilstellwert` | Bad OG Heizen Ventilstellwert | 38 | % |  |  |
| `sensor.bad_og_radiator_heizen_ventilstellwert` | Bad OG Radiator Heizen Ventilstellwert | 38 | % |  |  |
| `sensor.buro_test_heizen_ventilstellwert` | Büro test Heizen Ventilstellwert | 52 | % |  |  |
| `sensor.bus_spannungsmesswert` | Bus Spannungsmesswert | 30044.16 | mV | voltage |  |
| `sensor.bus_statusausgabe` | Bus Statusausgabe | unknown |  |  |  |
| `sensor.bus_statustext` | Bus Statustext | unknown |  |  |  |
| `sensor.bus_strommesswert` | Bus Strommesswert | 158 | mA | current |  |
| `sensor.busverkehr` | Busverkehr | 2 | % |  |  |
| `sensor.c386d1df8bbc_unnamed_app_last_heartbeat` | c386d1df8bbc unnamed_app Last Heartbeat | 2025-09-22T08:10:15.194181+00:00 |  |  |  |
| `sensor.cam_engel_day_night_state` | CAM_Engel Day night state | day |  | enum |  |
| `sensor.cam_terrasse_day_night_state` | CAM_Terrasse Day night state | day |  | enum |  |
| `sensor.devbox_192_168_0_51_jupyterlab_last_heartbeat` | devbox-192-168-0-51 jupyterlab Last Heartbeat | 2026-02-11T08:47:12.231128+00:00 |  |  |  |
| `sensor.devbox_192_168_0_51_pv_forecast_last_heartbeat` | devbox-192-168-0-51 pv_forecast Last Heartbeat | 2026-02-11T08:46:53.399039+00:00 |  |  |  |
| `sensor.dishwasher_door` | Door | unavailable |  | enum |  |
| `sensor.dishwasher_duration` | Duration | unavailable | s | duration |  |
| `sensor.dishwasher_operation_state` | Operation state | unavailable |  | enum |  |
| `sensor.dishwasher_program_finish_time` | Program finish time | unavailable |  | timestamp |  |
| `sensor.dishwasher_program_progress` | Program progress | unavailable | % |  |  |
| `sensor.dishwasher_rinse_aid_nearly_empty` | Rinse aid nearly empty | unavailable |  | enum |  |
| `sensor.dishwasher_salt_nearly_empty` | Salt nearly empty | unavailable |  | enum |  |
| `sensor.ds214_cpu_load_average_15_min` | ds214 CPU load average (15 min) | 1.41 | load |  |  |
| `sensor.ds214_cpu_load_average_5_min` | ds214 CPU load average (5 min) | 1.34 | load |  |  |
| `sensor.ds214_cpu_utilization_total` | ds214 CPU utilization (total) | 6 | % |  |  |
| `sensor.ds214_cpu_utilization_user` | ds214 CPU utilization (user) | 3 | % |  |  |
| `sensor.ds214_download_throughput` | ds214 Download throughput | 1.737 | kB/s | data_rate |  |
| `sensor.ds214_drive_1_status` | ds214 (Drive 1) Status | normal |  |  |  |
| `sensor.ds214_drive_1_temperature` | ds214 (Drive 1) Temperature | 27 | °C | temperature |  |
| `sensor.ds214_drive_2_status` | Status | unavailable |  |  |  |
| `sensor.ds214_drive_2_temperature` | Temperature | unavailable | °C | temperature |  |
| `sensor.ds214_memory_available_real` | ds214 Memory available (real) | 39.636992 | MB | data_size |  |
| `sensor.ds214_memory_available_swap` | ds214 Memory available (swap) | 1991.135232 | MB | data_size |  |
| `sensor.ds214_memory_total_real` | ds214 Memory total (real) | 526.934016 | MB | data_size |  |
| `sensor.ds214_memory_total_swap` | ds214 Memory total (swap) | 2147.414016 | MB | data_size |  |
| `sensor.ds214_memory_usage_real` | ds214 Memory usage (real) | 26 | % |  |  |
| `sensor.ds214_temperature` | ds214 Temperature | 29 | °C | temperature |  |
| `sensor.ds214_upload_throughput` | ds214 Upload throughput | 0.567 | kB/s | data_rate |  |
| `sensor.ds214_volume_1_average_disk_temp` | ds214 (Volume 1) Average disk temp | 28.0 | °C | temperature |  |
| `sensor.ds214_volume_1_status` | ds214 (Volume 1) Status | normal |  |  |  |
| `sensor.ds214_volume_1_used_space` | ds214 (Volume 1) Used space | 1.826618896384 | TB | data_size |  |
| `sensor.ds214_volume_1_volume_used` | ds214 (Volume 1) Volume used | 49.4 | % |  |  |
| `sensor.ds214_volume_2_average_disk_temp` | ds214 (Volume 2) Average disk temp | 28.0 | °C | temperature |  |
| `sensor.ds214_volume_2_status` | ds214 (Volume 2) Status | normal |  |  |  |
| `sensor.ds214_volume_2_used_space` | ds214 (Volume 2) Used space | 0.00132448256 | TB | data_size |  |
| `sensor.ds214_volume_2_volume_used` | ds214 (Volume 2) Volume used | 0.0 | % |  |  |
| `sensor.electricity_maps_co2_intensity` | Electricity Maps CO2 intensity | 455.0 | gCO2eq/kWh |  |  |
| `sensor.electricity_maps_grid_fossil_fuel_percentage` | Electricity Maps Grid fossil fuel percentage | 52.62 | % |  |  |
| `sensor.energy_current_hour_east` | balkon_east Estimated energy production - this hour | 1.015 | kWh | energy |  |
| `sensor.energy_current_hour_west` | balkon_west Estimated energy production - this hour | 0.676 | kWh | energy |  |
| `sensor.energy_meter_wohnzimmer_heating_wh` | energy_meter_wohnzimmer_heating_wh | 0 | kWh | energy |  |
| `sensor.energy_next_hour_east` | balkon_east Estimated energy production - next hour | 1.548 | kWh | energy |  |
| `sensor.energy_next_hour_west` | balkon_west Estimated energy production - next hour | 1.113 | kWh | energy |  |
| `sensor.energy_production_today_east` | balkon_east Estimated energy production - today | 12.018 | kWh | energy |  |
| `sensor.energy_production_today_remaining_east` | balkon_east Estimated energy production - remaining today | 11.33 | kWh | energy |  |
| `sensor.energy_production_today_remaining_west` | balkon_west Estimated energy production - remaining today | 10.528 | kWh | energy |  |
| `sensor.energy_production_today_west` | balkon_west Estimated energy production - today | 10.969 | kWh | energy |  |
| `sensor.energy_production_tomorrow_east` | balkon_east Estimated energy production - tomorrow | 12.176 | kWh | energy |  |
| `sensor.energy_production_tomorrow_west` | balkon_west Estimated energy production - tomorrow | 11.114 | kWh | energy |  |
| `sensor.energy_production_total_east_est` | energy_production_total_east_est | 3277.163841362092780156139279 | kWh | energy |  |
| `sensor.energy_production_total_west_est` | energy_production_total_west_est | 2907.101528510958056463020469 | kWh | energy |  |
| `sensor.epex_spot_data_average_price` | EPEX Spot Data Average Price | 0.1125375 | €/kWh |  |  |
| `sensor.epex_spot_data_average_price_2` | EPEX Spot Data Average Price | 0.1125375 | €/kWh |  |  |
| `sensor.epex_spot_data_highest_price` | EPEX Spot Data Highest Price | 0.13707 | €/kWh |  |  |
| `sensor.epex_spot_data_highest_price_2` | EPEX Spot Data Highest Price | 0.13707 | €/kWh |  |  |
| `sensor.epex_spot_data_lowest_price` | EPEX Spot Data Lowest Price | 0.09468 | €/kWh |  |  |
| `sensor.epex_spot_data_lowest_price_2` | EPEX Spot Data Lowest Price | 0.09468 | €/kWh |  |  |
| `sensor.epex_spot_data_median_price` | EPEX Spot Data Median Price | 0.11394 | €/kWh |  |  |
| `sensor.epex_spot_data_median_price_2` | EPEX Spot Data Median Price | 0.11394 | €/kWh |  |  |
| `sensor.epex_spot_data_net_price` | EPEX Spot Data Net Price | 0.303073 | €/kWh |  |  |
| `sensor.epex_spot_data_net_price_2` | EPEX Spot Data Net Price | 0.303073 | €/kWh |  |  |
| `sensor.epex_spot_data_price` | EPEX Spot Data Price | 0.13144 | €/kWh |  |  |
| `sensor.epex_spot_data_price_2` | EPEX Spot Data Price | 0.13144 | €/kWh |  |  |
| `sensor.epex_spot_data_quantile` | EPEX Spot Data Quantile | 0.867185656994574 |  |  |  |
| `sensor.epex_spot_data_quantile_2` | EPEX Spot Data Quantile | 0.867185656994574 |  |  |  |
| `sensor.epex_spot_data_rank` | EPEX Spot Data Rank | 22 |  |  |  |
| `sensor.epex_spot_data_rank_2` | EPEX Spot Data Rank | 22 |  |  |  |
| `sensor.esszimmer_kuche_wand` | Esszimmer/Küche Wand | 18.3 | °C | temperature |  |
| `sensor.ev_boost_remaining_kwh` | EV boost remaining kWh | unavailable | kWh |  |  |
| `sensor.ev_charge_energy_daily` | ev_charge_energy_daily | unavailable | kWh | energy |  |
| `sensor.ev_charging_energy_kwh` | EV charging energy (kWh) | unavailable | kWh | energy |  |
| `sensor.ev_grid_export_w` | EV grid export W | unavailable | W |  |  |
| `sensor.ev_max_power_w` | EV max power W | unavailable | W |  |  |
| `sensor.ev_min_power_w` | EV min power W | unavailable | W |  |  |
| `sensor.ev_min_power_w_calc` | EV min power W (calc) | unavailable | W |  |  |
| `sensor.ev_surplus_target_w_raw` | EV surplus target W (raw) | unavailable | W |  |  |
| `sensor.feuchte_bad_eg_rel` | Feuchte Bad EG (rel) | 57.4 | % | humidity |  |
| `sensor.feuchte_bad_og_abs` | Feuchte Bad OG (abs) | 9.8 | g/m³ | humidity |  |
| `sensor.feuchte_bad_og_rel` | Feuchte Bad OG (rel) | 57.08 | % | humidity |  |
| `sensor.feuchte_wohnzimmer_rel` | Feuchte Wohnzimmer (rel) | 47.6 | % | humidity |  |
| `sensor.guest_wc_temperature_stable` | Guest WC Temperature (Stable) | unavailable | °C | temperature |  |
| `sensor.hennings_cg_iphone_activity` | Henning’s CG iphone Activity | Stationary |  |  |  |
| `sensor.hennings_cg_iphone_average_active_pace` | Henning’s CG iphone Average Active Pace | 1 | m/s |  |  |
| `sensor.hennings_cg_iphone_battery_level` | Henning’s CG iphone Battery Level | 62 | % | battery |  |
| `sensor.hennings_cg_iphone_battery_state` | Henning’s CG iphone Battery State | Not Charging |  |  |  |
| `sensor.hennings_cg_iphone_bssid` | Henning’s CG iphone BSSID | 34:31:c4:1f:c0:48 |  |  |  |
| `sensor.hennings_cg_iphone_connection_type` | Henning’s CG iphone Connection Type | Wi-Fi |  |  |  |
| `sensor.hennings_cg_iphone_distance` | Henning’s CG iphone Distance | 0 | m |  |  |
| `sensor.hennings_cg_iphone_floors_ascended` | Henning’s CG iphone Floors Ascended | 0 | floors |  |  |
| `sensor.hennings_cg_iphone_floors_descended` | Henning’s CG iphone Floors Descended | 0 | floors |  |  |
| `sensor.hennings_cg_iphone_geocoded_location` | Henning’s CG iphone Geocoded Location | Isaak-Winkler-Weg 12 49477 Ibbenbüren G… |  |  |  |
| `sensor.hennings_cg_iphone_last_update_trigger` | Henning’s CG iphone Last Update Trigger | Periodic |  |  |  |
| `sensor.hennings_cg_iphone_sim_1` | Henning’s CG iphone SIM 1 | Telekom.de |  |  |  |
| `sensor.hennings_cg_iphone_sim_2` | Henning’s CG iphone SIM 2 | N/A |  |  |  |
| `sensor.hennings_cg_iphone_ssid` | Henning’s CG iphone SSID | schuettken |  |  |  |
| `sensor.hennings_cg_iphone_steps` | Henning’s CG iphone Steps | 0 | steps |  |  |
| `sensor.hennings_cg_iphone_storage` | Henning’s CG iphone Storage | 44.17 | % available |  |  |
| `sensor.hennings_iphone_activity` | Henning’s iPhone Activity | Unknown |  |  |  |
| `sensor.hennings_iphone_app_version` | Henning’s iPhone App Version | 2026.1.1 |  |  |  |
| `sensor.hennings_iphone_audio_output` | Henning’s iPhone Audio Output | Built-in Speaker |  |  |  |
| `sensor.hennings_iphone_average_active_pace` | Henning’s iPhone Average Active Pace | 3 | m/s |  |  |
| `sensor.hennings_iphone_battery_level` | Henning’s iPhone Battery Level | 95 | % | battery |  |
| `sensor.hennings_iphone_battery_state` | Henning’s iPhone Battery State | Not Charging |  |  |  |
| `sensor.hennings_iphone_bssid` | Henning’s iPhone BSSID | 20:36:26:d4:91:91 |  |  |  |
| `sensor.hennings_iphone_connection_type` | Henning’s iPhone Connection Type | Wi-Fi |  |  |  |
| `sensor.hennings_iphone_distance` | Henning’s iPhone Distance | 26 | m |  |  |
| `sensor.hennings_iphone_floors_ascended` | Henning’s iPhone Floors Ascended | 0 | floors |  |  |
| `sensor.hennings_iphone_floors_descended` | Henning’s iPhone Floors Descended | 0 | floors |  |  |
| `sensor.hennings_iphone_geocoded_location` | Henning’s iPhone Geocoded Location | Nierenburger Straße 9 49497 Mettingen G… |  |  |  |
| `sensor.hennings_iphone_last_update_trigger` | Henning’s iPhone Last Update Trigger | Background Fetch |  |  |  |
| `sensor.hennings_iphone_location_permission` | Henning’s iPhone Location permission | Authorized Always |  |  |  |
| `sensor.hennings_iphone_sim_1` | Henning’s iPhone SIM 1 | -- |  |  |  |
| `sensor.hennings_iphone_sim_2` | Henning’s iPhone SIM 2 | -- |  |  |  |
| `sensor.hennings_iphone_ssid` | Henning’s iPhone SSID | NB9 |  |  |  |
| `sensor.hennings_iphone_steps` | Henning’s iPhone Steps | 32 | steps |  |  |
| `sensor.hennings_iphone_storage` | Henning’s iPhone Storage | 11.18 | % available |  |  |
| `sensor.inverter_pv_1_power` | inverter_pv_1_power | 155.142 | W | power |  |
| `sensor.inverter_pv_2_power` | inverter_pv_2_power | 115.362 | W | power |  |
| `sensor.inverter_pv_3_power` | inverter_pv_3_power | 138.138 | W | power |  |
| `sensor.inverter_pv_4_power` | inverter_pv_4_power | 138.138 | W | power |  |
| `sensor.inverter_pv_east_energy` | inverter_pv_east_energy | 1281.08 | kWh | energy |  |
| `sensor.inverter_pv_east_power` | inverter_pv_east_power | 270.504 | W | power |  |
| `sensor.inverter_pv_west_energy` | inverter_pv_west_energy | 1116.63 | kWh | energy |  |
| `sensor.inverter_pv_west_power` | inverter_pv_west_power | 276.276 | W | power |  |
| `sensor.iphone16_hp_hs_app_version` | iPhone16 HP HS App Version | 2026.2.1 |  |  |  |
| `sensor.iphone16_hp_hs_audio_output` | iPhone16 HP HS Audio Output | unavailable |  |  |  |
| `sensor.iphone16_hp_hs_battery_level` | iPhone16 HP HS Battery Level | 50 | % | battery |  |
| `sensor.iphone16_hp_hs_battery_state` | iPhone16 HP HS Battery State | Not Charging |  |  |  |
| `sensor.iphone16_hp_hs_bssid` | iPhone16 HP HS BSSID | unavailable |  |  |  |
| `sensor.iphone16_hp_hs_connection_type` | iPhone16 HP HS Connection Type | unavailable |  |  |  |
| `sensor.iphone16_hp_hs_geocoded_location` | iPhone16 HP HS Geocoded Location | unavailable |  |  |  |
| `sensor.iphone16_hp_hs_last_update_trigger` | iPhone16 HP HS Last Update Trigger | unavailable |  |  |  |
| `sensor.iphone16_hp_hs_location_permission` | iPhone16 HP HS Location permission | Not determined |  |  |  |
| `sensor.iphone16_hp_hs_sim_1` | iPhone16 HP HS SIM 1 | unavailable |  |  |  |
| `sensor.iphone16_hp_hs_sim_2` | iPhone16 HP HS SIM 2 | unavailable |  |  |  |
| `sensor.iphone16_hp_hs_ssid` | iPhone16 HP HS SSID | unavailable |  |  |  |
| `sensor.iphone16_hp_hs_storage` | iPhone16 HP HS Storage | unavailable | % available |  |  |
| `sensor.iphone8_activity` | iPhone8 Activity | Stationary |  |  |  |
| `sensor.iphone8_app_version` | iPhone8 App Version | 2024.9.4 |  |  |  |
| `sensor.iphone8_average_active_pace` | iPhone8 Average Active Pace | 1 | m/s |  |  |
| `sensor.iphone8_battery_level` | iPhone8 Battery Level | 85 | % | battery |  |
| `sensor.iphone8_battery_state` | iPhone8 Battery State | Not Charging |  |  |  |
| `sensor.iphone8_bssid` | iPhone8 BSSID | 50:91:e3:e3:df:83 |  |  |  |
| `sensor.iphone8_connection_type` | iPhone8 Connection Type | Wi-Fi |  |  |  |
| `sensor.iphone8_distance` | iPhone8 Distance | 0 | m |  |  |
| `sensor.iphone8_floors_ascended` | iPhone8 Floors Ascended | 0 | floors |  |  |
| `sensor.iphone8_floors_descended` | iPhone8 Floors Descended | 0 | floors |  |  |
| `sensor.iphone8_geocoded_location` | iPhone8 Geocoded Location | Nierenburger Straße 9 49497 Mettingen G… |  |  |  |
| `sensor.iphone8_last_update_trigger` | iPhone8 Last Update Trigger | Periodic |  |  |  |
| `sensor.iphone8_location_permission` | iPhone8 Location permission | Authorized Always |  |  |  |
| `sensor.iphone8_sim_1` | iPhone8 SIM 1 | -- |  |  |  |
| `sensor.iphone8_ssid` | iPhone8 SSID | NB9 |  |  |  |
| `sensor.iphone8_steps` | iPhone8 Steps | 0 | steps |  |  |
| `sensor.iphone8_storage` | iPhone8 Storage | 24.12 | % available |  |  |
| `sensor.iphone_13_cgp_activity` | iPhone 13 CGp Activity | Walking |  |  |  |
| `sensor.iphone_13_cgp_average_active_pace` | iPhone 13 CGp Average Active Pace | 1 | m/s |  |  |
| `sensor.iphone_13_cgp_battery_level` | iPhone 13 CGp Battery Level | 80 | % | battery |  |
| `sensor.iphone_13_cgp_battery_state` | iPhone 13 CGp Battery State | Not Charging |  |  |  |
| `sensor.iphone_13_cgp_bssid` | iPhone 13 CGp BSSID | f0:a7:31:a1:f6:85 |  |  |  |
| `sensor.iphone_13_cgp_connection_type` | iPhone 13 CGp Connection Type | Wi-Fi |  |  |  |
| `sensor.iphone_13_cgp_distance` | iPhone 13 CGp Distance | 136 | m |  |  |
| `sensor.iphone_13_cgp_floors_ascended` | iPhone 13 CGp Floors Ascended | 1 | floors |  |  |
| `sensor.iphone_13_cgp_floors_descended` | iPhone 13 CGp Floors Descended | 2 | floors |  |  |
| `sensor.iphone_13_cgp_geocoded_location` | iPhone 13 CGp Geocoded Location | Nierenburger Straße 9 49497 Mettingen G… |  |  |  |
| `sensor.iphone_13_cgp_last_update_trigger` | iPhone 13 CGp Last Update Trigger | Periodic |  |  |  |
| `sensor.iphone_13_cgp_sim_1` | iPhone 13 CGp SIM 1 | -- |  |  |  |
| `sensor.iphone_13_cgp_sim_2` | iPhone 13 CGp SIM 2 | -- |  |  |  |
| `sensor.iphone_13_cgp_ssid` | iPhone 13 CGp SSID | NB9 |  |  |  |
| `sensor.iphone_13_cgp_steps` | iPhone 13 CGp Steps | 198 | steps |  |  |
| `sensor.iphone_13_cgp_storage` | iPhone 13 CGp Storage | 92.69 | % available |  |  |
| `sensor.keller_flur_treppe_v3_basement_stairs_humidity` | keller_flur_treppe_v3 Basement stairs Humidity | 64.8000030517578 | % | humidity |  |
| `sensor.keller_flur_treppe_v3_basement_stairs_temperature` | Kellertreppe temp | 12.6999998092651 | °C | temperature |  |
| `sensor.lux_bad_og_rel` | Lux Bad OG | 19.09 | lx | illuminance |  |
| `sensor.lux_flur_og` | Lux Flur OG | 8.36 | lx | illuminance |  |
| `sensor.lux_wohnzimmer` | Lux Wohnzimmer | 24.18 | lx | illuminance |  |
| `sensor.market_grid_price_status` | Market Grid Price Status | 1 |  |  |  |
| `sensor.measured_power_energy` | Measured power energy | 9985.08 | kWh |  |  |
| `sensor.monthly_calculated_energy_consumption_house` | monthly_calculated_energy_consumption_house | unavailable | W |  |  |
| `sensor.openweathermap_cloud_coverage` | OpenWeatherMap Cloud coverage | 100 | % |  |  |
| `sensor.openweathermap_condition` | OpenWeatherMap Condition | rainy |  |  |  |
| `sensor.openweathermap_dew_point` | OpenWeatherMap Dew Point | 6.91 | °C | temperature |  |
| `sensor.openweathermap_feels_like_temperature` | OpenWeatherMap Feels like temperature | 6.08 | °C | temperature |  |
| `sensor.openweathermap_humidity` | OpenWeatherMap Humidity | 100 | % | humidity |  |
| `sensor.openweathermap_precipitation_kind` | OpenWeatherMap Precipitation kind | None |  |  |  |
| `sensor.openweathermap_pressure` | OpenWeatherMap Pressure | 983 | hPa | pressure |  |
| `sensor.openweathermap_rain` | OpenWeatherMap Rain | 0 | mm/h | precipitation_intensity |  |
| `sensor.openweathermap_snow` | OpenWeatherMap Snow | 0 | mm/h | precipitation_intensity |  |
| `sensor.openweathermap_temperature` | OpenWeatherMap Temperature | 6.91 | °C | temperature |  |
| `sensor.openweathermap_uv_index` | OpenWeatherMap UV Index | 0.06 | UV index |  |  |
| `sensor.openweathermap_visibility` | OpenWeatherMap Visibility | 3700 | m | distance |  |
| `sensor.openweathermap_weather` | OpenWeatherMap Weather | light intensity drizzle |  |  |  |
| `sensor.openweathermap_weather_code` | OpenWeatherMap Weather Code | 300 |  |  |  |
| `sensor.openweathermap_wind_bearing` | OpenWeatherMap Wind bearing | 110 | ° | wind_direction |  |
| `sensor.openweathermap_wind_gust` | OpenWeatherMap Wind gust | unknown | km/h | wind_speed |  |
| `sensor.openweathermap_wind_speed` | OpenWeatherMap Wind speed | 5.544 | km/h | wind_speed |  |
| `sensor.outside_v2_absolute_humidity` | Outside v2 Absolute humidity | 7.7025219549091 | g/m³ |  |  |
| `sensor.outside_v2_dew_point` | Outside v2 Dew point | 6.91477305971412 | °C | temperature |  |
| `sensor.outside_v2_dew_point_perception` | Outside v2 Dew point perception | dry |  | enum |  |
| `sensor.outside_v2_frost_point` | Outside v2 Frost point | 6.06241712684783 | °C | temperature |  |
| `sensor.outside_v2_frost_risk` | Outside v2 Frost risk | no_risk |  | enum |  |
| `sensor.outside_v2_heat_index` | Outside v2 Heat index | 6.26766666666667 | °C | temperature |  |
| `sensor.outside_v2_humidex` | Outside v2 Humidex | 6.88961645701843 | °C | temperature |  |
| `sensor.outside_v2_humidex_perception` | Outside v2 Humidex perception | comfortable |  | enum |  |
| `sensor.outside_v2_moist_air_enthalpy` | Outside v2 Moist air enthalpy | 22.4692997379146 | kJ/kg |  |  |
| `sensor.outside_v2_relative_strain_perception` | Outside v2 Relative strain perception | outside_calculable_range |  | enum |  |
| `sensor.outside_v2_summer_scharlau_perception` | Outside v2 Summer Scharlau perception | outside_calculable_range |  | enum |  |
| `sensor.outside_v2_summer_simmer_index` | Outside v2 Summer Simmer index | 6.91 | °C | temperature |  |
| `sensor.outside_v2_summer_simmer_perception` | Outside v2 Summer Simmer perception | cool |  | enum |  |
| `sensor.outside_v2_thoms_discomfort_perception` | Outside v2 Thoms discomfort perception | no_discomfort |  | enum |  |
| `sensor.outside_v2_winter_scharlau_perception` | Outside v2 Winter Scharlau perception | outside_calculable_range |  | enum |  |
| `sensor.power_highest_peak_time_today_east` | balkon_east Highest power peak time - today | 2026-02-11T11:00:00+00:00 |  | timestamp |  |
| `sensor.power_highest_peak_time_today_west` | balkon_west Highest power peak time - today | 2026-02-11T12:00:00+00:00 |  | timestamp |  |
| `sensor.power_highest_peak_time_tomorrow_east` | balkon_east Highest power peak time - tomorrow | 2026-02-12T11:00:00+00:00 |  | timestamp |  |
| `sensor.power_highest_peak_time_tomorrow_west` | balkon_west Highest power peak time - tomorrow | 2026-02-12T12:00:00+00:00 |  | timestamp |  |
| `sensor.power_production_next_12hours_east` | balkon_east Estimated power production - in 12 hours | 0 | W | power |  |
| `sensor.power_production_next_12hours_west` | balkon_west Estimated power production - in 12 hours | 0 | W | power |  |
| `sensor.power_production_next_24hours_east` | balkon_east Estimated power production - in 24 hours | 1049 | W | power |  |
| `sensor.power_production_next_24hours_west` | balkon_west Estimated power production - in 24 hours | 693 | W | power |  |
| `sensor.power_production_next_hour_east` | balkon_east Estimated power production - in 1 hour | 1565 | W | power |  |
| `sensor.power_production_next_hour_west` | balkon_west Estimated power production - in 1 hour | 1123 | W | power |  |
| `sensor.power_production_now_east` | balkon_east Estimated power production - now | 1031 | W | power |  |
| `sensor.power_production_now_west` | balkon_west Estimated power production - now | 682 | W | power |  |
| `sensor.price_per_kwh_electricity_grid_eur` | price_per_kwh_electricity_grid_eur | 0.2611 | €/kWh |  |  |
| `sensor.pv_ai_forecast_day_after_tomorrow_kwh` | PV AI Forecast Day After Tomorrow | 14.42 | kWh | energy |  |
| `sensor.pv_ai_forecast_east_today_kwh` | PV AI Forecast East Today | 5.98 | kWh | energy |  |
| `sensor.pv_ai_forecast_east_tomorrow_kwh` | PV AI Forecast East Tomorrow | 15.04 | kWh | energy |  |
| `sensor.pv_ai_forecast_pv_forecast_day_after_tomorrow` | PV AI Forecast PV Forecast Day After Tomorrow | 14.42 | kWh | energy |  |
| `sensor.pv_ai_forecast_pv_forecast_today` | PV AI Forecast PV Forecast Today | 11.97 | kWh | energy |  |
| `sensor.pv_ai_forecast_pv_forecast_today_remaining` | PV AI Forecast PV Forecast Today Remaining | 10.3 | kWh | energy |  |
| `sensor.pv_ai_forecast_pv_forecast_tomorrow` | PV AI Forecast PV Forecast Tomorrow | 25.59 | kWh | energy |  |
| `sensor.pv_ai_forecast_pv_forecast_uptime` | PV AI Forecast PV Forecast Uptime | 236772 | s | duration |  |
| `sensor.pv_ai_forecast_today_kwh` | PV AI Forecast Today | 11.97 | kWh | energy |  |
| `sensor.pv_ai_forecast_today_remaining_kwh` | PV AI Forecast Today Remaining | 10.3 | kWh | energy |  |
| `sensor.pv_ai_forecast_tomorrow_kwh` | PV AI Forecast Tomorrow | 25.59 | kWh | energy |  |
| `sensor.pv_ai_forecast_west_today_kwh` | PV AI Forecast West Today | 5.99 | kWh | energy |  |
| `sensor.pv_ai_forecast_west_tomorrow_kwh` | PV AI Forecast West Tomorrow | 10.55 | kWh | energy |  |
| `sensor.pv_electricity_price_market_adjusted` | PV Electricity Price (Market Adjusted) | 0.0723 | €/kWh |  |  |
| `sensor.redminote13_battery_level` | redminote13 Battery level | 11 | % | battery |  |
| `sensor.redminote13_battery_state` | redminote13 Battery state | charging |  | enum |  |
| `sensor.redminote13_charger_type` | redminote13 Charger type | ac |  | enum |  |
| `sensor.rudiger_battery` | Battery | unavailable | % | battery |  |
| `sensor.rudiger_cleaning_area` | Cleaning area | unavailable | m² |  |  |
| `sensor.rudiger_cleaning_time` | Cleaning time | unavailable | s | duration |  |
| `sensor.rudiger_filter_time_left` | Filter time left | unavailable | s | duration |  |
| `sensor.rudiger_last_clean_begin` | Last clean begin | unavailable |  | timestamp |  |
| `sensor.rudiger_last_clean_end` | Last clean end | unavailable |  | timestamp |  |
| `sensor.rudiger_main_brush_time_left` | Main brush time left | unavailable | s | duration |  |
| `sensor.rudiger_sensor_time_left` | Sensor time left | unavailable | s | duration |  |
| `sensor.rudiger_side_brush_time_left` | Side brush time left | unavailable | s | duration |  |
| `sensor.rudiger_status` | Status | unavailable |  | enum |  |
| `sensor.rudiger_total_cleaning_area` | Total cleaning area | unavailable | m² |  |  |
| `sensor.rudiger_total_cleaning_time` | Total cleaning time | unavailable | s | duration |  |
| `sensor.rudiger_vacuum_error` | Vacuum error | unavailable |  | enum |  |
| `sensor.schmohlchens_iphone_activity` | Schmöhlchens iPhone Activity | Unknown |  |  |  |
| `sensor.schmohlchens_iphone_app_version` | Schmöhlchens iPhone App Version | 2026.1.1 |  |  |  |
| `sensor.schmohlchens_iphone_audio_output` | Schmöhlchens iPhone Audio Output | Built-in Speaker |  |  |  |
| `sensor.schmohlchens_iphone_average_active_pace` | Schmöhlchens iPhone Average Active Pace | 0 | m/s |  |  |
| `sensor.schmohlchens_iphone_battery_level` | Schmöhlchens iPhone Battery Level | 95 | % | battery |  |
| `sensor.schmohlchens_iphone_battery_state` | Schmöhlchens iPhone Battery State | Not Charging |  |  |  |
| `sensor.schmohlchens_iphone_bssid` | Schmöhlchens iPhone BSSID | Not Connected |  |  |  |
| `sensor.schmohlchens_iphone_connection_type` | Schmöhlchens iPhone Connection Type | Cellular |  |  |  |
| `sensor.schmohlchens_iphone_distance` | Schmöhlchens iPhone Distance | 248 | m |  |  |
| `sensor.schmohlchens_iphone_floors_ascended` | Schmöhlchens iPhone Floors Ascended | 3 | floors |  |  |
| `sensor.schmohlchens_iphone_floors_descended` | Schmöhlchens iPhone Floors Descended | 1 | floors |  |  |
| `sensor.schmohlchens_iphone_geocoded_location` | Schmöhlchens iPhone Geocoded Location | Nierenburger Straße 9 49497 Mettingen G… |  |  |  |
| `sensor.schmohlchens_iphone_last_update_trigger` | Schmöhlchens iPhone Last Update Trigger | Background Fetch |  |  |  |
| `sensor.schmohlchens_iphone_location_permission` | Schmöhlchens iPhone Location permission | Authorized when in use |  |  |  |
| `sensor.schmohlchens_iphone_sim_1` | Schmöhlchens iPhone SIM 1 | -- |  |  |  |
| `sensor.schmohlchens_iphone_sim_2` | Schmöhlchens iPhone SIM 2 | -- |  |  |  |
| `sensor.schmohlchens_iphone_ssid` | Schmöhlchens iPhone SSID | Not Connected |  |  |  |
| `sensor.schmohlchens_iphone_steps` | Schmöhlchens iPhone Steps | 361 | steps |  |  |
| `sensor.schmohlchens_iphone_storage` | Schmöhlchens iPhone Storage | 30.17 | % available |  |  |
| `sensor.shelly3em_main_channel_total_energy` | shelly3em_main_channel_total_energy | 10039.5568 | kWh | energy |  |
| `sensor.shelly3em_main_channel_total_power` | shelly3em_main_channel_total_power | 526.27 | W | power |  |
| `sensor.shelly_keller_flur_switch_0_energy` | Shelly_Keller_Flur switch_0 energy | 31.615228 | kWh | energy |  |
| `sensor.shelly_keller_flur_switch_0_power` | Shelly_Keller_Flur switch_0 power | 0.0 | W | power |  |
| `sensor.smart_ev_charging_actual_power` | Smart EV Charging Actual Power | 0 | W | power |  |
| `sensor.smart_ev_charging_charge_mode` | Smart EV Charging Charge Mode | Smart |  |  |  |
| `sensor.smart_ev_charging_home_battery_power` | Smart EV Charging Home Battery Power | 0 | W | power |  |
| `sensor.smart_ev_charging_home_battery_soc` | Smart EV Charging Home Battery SoC | 5.0 | % | battery |  |
| `sensor.smart_ev_charging_house_power` | Smart EV Charging House Power | 549 | W | power |  |
| `sensor.smart_ev_charging_pv_available_for_ev` | Smart EV Charging PV Available for EV | 0 | W | power |  |
| `sensor.smart_ev_charging_session_energy` | Smart EV Charging Session Energy | 48.09 | kWh | energy |  |
| `sensor.smart_ev_charging_status` | Smart EV Charging Status | No vehicle connected |  |  |  |
| `sensor.smart_ev_charging_target_power` | Smart EV Charging Target Power | 0 | W | power |  |
| `sensor.solar_production_estimated_now_all` | solar_production_estimated_now_all | 1713.0 | W |  |  |
| `sensor.speedtest_download` | SpeedTest Download | 301.24 | Mbit/s | data_rate |  |
| `sensor.speedtest_ping` | SpeedTest Ping | 15 | ms | duration |  |
| `sensor.speedtest_upload` | SpeedTest Upload | 135.45 | Mbit/s | data_rate |  |
| `sensor.sun_next_dawn` | Sun Next dawn | 2026-02-12T06:14:39+00:00 |  | timestamp |  |
| `sensor.sun_next_dusk` | Sun Next dusk | 2026-02-11T17:10:31+00:00 |  | timestamp |  |
| `sensor.sun_next_midnight` | Sun Next midnight | 2026-02-11T23:43:05+00:00 |  | timestamp |  |
| `sensor.sun_next_noon` | Sun Next noon | 2026-02-11T11:43:05+00:00 |  | timestamp |  |
| `sensor.sun_next_rising` | Sun Next rising | 2026-02-12T06:50:52+00:00 |  | timestamp |  |
| `sensor.sun_next_setting` | Sun Next setting | 2026-02-11T16:34:07+00:00 |  | timestamp |  |
| `sensor.sun_solar_azimuth` | Sun Solar azimuth | 135.87 | ° |  |  |
| `sensor.sun_solar_elevation` | Sun Solar elevation | 13.59 | ° |  |  |
| `sensor.system_monitor_disk_free` | System Monitor Disk free / | 21.9 | GiB | data_size |  |
| `sensor.system_monitor_disk_usage` | System Monitor Disk usage / | 81.8 | % |  |  |
| `sensor.system_monitor_disk_use` | System Monitor Disk use / | 98.2 | GiB | data_size |  |
| `sensor.system_monitor_ipv4_address_enp0s18` | System Monitor IPv4 address enp0s18 | 192.168.0.40 |  |  |  |
| `sensor.system_monitor_load_15m` | System Monitor Load (15 min) | 0.0 |  |  |  |
| `sensor.system_monitor_load_1m` | System Monitor Load (1 min) | 0.0 |  |  |  |
| `sensor.system_monitor_load_5m` | System Monitor Load (5 min) | 0.0 |  |  |  |
| `sensor.system_monitor_memory_free` | System Monitor Memory free | 6269.5 | MiB | data_size |  |
| `sensor.system_monitor_memory_usage` | System Monitor Memory usage | 21.0 | % |  |  |
| `sensor.system_monitor_memory_use` | System Monitor Memory use | 1670.6 | MiB | data_size |  |
| `sensor.system_monitor_network_in_enp0s18` | System Monitor Network in enp0s18 | 720776.8 | MiB | data_size |  |
| `sensor.system_monitor_network_out_enp0s18` | System Monitor Network out enp0s18 | 313385.7 | MiB | data_size |  |
| `sensor.system_monitor_network_throughput_in_enp0s18` | System Monitor Network throughput in enp0s18 | 0.006 | MB/s | data_rate |  |
| `sensor.system_monitor_network_throughput_out_enp0s18` | System Monitor Network throughput out enp0s18 | 0.005 | MB/s | data_rate |  |
| `sensor.system_monitor_packets_in_enp0s18` | System Monitor Packets in enp0s18 | 585778659 |  |  |  |
| `sensor.system_monitor_packets_out_enp0s18` | System Monitor Packets out enp0s18 | 474444663 |  |  |  |
| `sensor.system_monitor_processor_use` | System Monitor Processor use | 1 | % |  |  |
| `sensor.system_monitor_swap_free` | System Monitor Swap free | 2521.8 | MiB | data_size |  |
| `sensor.system_monitor_swap_usage` | System Monitor Swap usage | 3.8 | % |  |  |
| `sensor.system_monitor_swap_use` | System Monitor Swap use | 98.2 | MiB | data_size |  |
| `sensor.terassentur` | Terassentür | 18.6 | °C | temperature |  |
| `sensor.test2` | test2 | 1505.33 | kWh | energy |  |
| `sensor.washer_current_status` | Washer Current status | power_off |  | enum |  |
| `sensor.washer_cycles` | Washer Cycles | 31 |  |  |  |
| `sensor.washer_delay_ends_in` | Washer Delayed end | unknown |  | timestamp |  |
| `sensor.washer_remaining_time` | Washer Remaining time | unknown |  | timestamp |  |
| `sensor.washer_total_time` | Washer Total time | unknown | min | duration |  |
| `sensor.watchman_last_updated` | watchman_last_updated | 2026-02-11T04:17:11+00:00 |  | timestamp |  |
| `sensor.watchman_missing_entities` | watchman_missing_entities | 6 | items |  |  |
| `sensor.watchman_missing_services` | watchman_missing_services | 1 | items |  |  |
| `sensor.wohnzimmer_heating_wh` | wohnzimmer_heating_wh | 1509.823 | kWh | energy |  |
| `sensor.wohnzimmer_heizen_ventilstellwert` | Wohnzimmer Heizen Ventilstellwert | 30 | % |  |  |

### binary_sensor

99 entities

| Entity ID | Name | State | Unit | Class | Area |
|-----------|------|-------|------|-------|------|
| `binary_sensor.shelly3em_main_overpowering` | shelly3em_main Overpowering | off |  | problem | mechanical |
| `binary_sensor.abstellraum_fenster` | Abstellraum Fenster | off |  | window |  |
| `binary_sensor.amtron_available_tpl` | Amtron Available (tpl) | on |  |  |  |
| `binary_sensor.amtron_plug_locked_tpl` | Amtron Plug Locked (tpl) | off |  |  |  |
| `binary_sensor.amtron_relay_on_tpl` | Amtron Relay On (tpl) | off |  |  |  |
| `binary_sensor.ankleide_fenster` | Ankleide Fenster | off |  | window |  |
| `binary_sensor.audi_a6_avant_e_tron_doors` | Audi A6 Avant e-tron Doors | unknown |  | door |  |
| `binary_sensor.audi_a6_avant_e_tron_doors_lock` | Audi A6 Avant e-tron Doors lock | unknown |  | lock |  |
| `binary_sensor.audi_a6_avant_e_tron_hood` | Audi A6 Avant e-tron Hood | unknown |  | door |  |
| `binary_sensor.audi_a6_avant_e_tron_left_front_door` | Audi A6 Avant e-tron Left front door | unknown |  | door |  |
| `binary_sensor.audi_a6_avant_e_tron_left_front_window` | Audi A6 Avant e-tron Left front window | unknown |  | window |  |
| `binary_sensor.audi_a6_avant_e_tron_left_rear_door` | Audi A6 Avant e-tron Left rear door | unknown |  | door |  |
| `binary_sensor.audi_a6_avant_e_tron_left_rear_window` | Audi A6 Avant e-tron Left rear window | unknown |  | window |  |
| `binary_sensor.audi_a6_avant_e_tron_parking_light` | Audi A6 Avant e-tron Parking light | unknown |  | safety |  |
| `binary_sensor.audi_a6_avant_e_tron_plug_lock_state` | Audi A6 Avant e-tron Plug Lock state | off |  | lock |  |
| `binary_sensor.audi_a6_avant_e_tron_plug_state` | Audi A6 Avant e-tron Plug state | on |  | plug |  |
| `binary_sensor.audi_a6_avant_e_tron_right_front_door` | Audi A6 Avant e-tron Right front door | unknown |  | door |  |
| `binary_sensor.audi_a6_avant_e_tron_right_front_window` | Audi A6 Avant e-tron Right front window | unknown |  | window |  |
| `binary_sensor.audi_a6_avant_e_tron_right_rear_door` | Audi A6 Avant e-tron Right rear door | unknown |  | door |  |
| `binary_sensor.audi_a6_avant_e_tron_right_rear_window` | Audi A6 Avant e-tron Right rear window | unknown |  | window |  |
| `binary_sensor.audi_a6_avant_e_tron_trunk` | Audi A6 Avant e-tron Trunk | unknown |  | door |  |
| `binary_sensor.audi_a6_avant_e_tron_trunk_lock` | Audi A6 Avant e-tron Trunk lock | unknown |  | lock |  |
| `binary_sensor.audi_a6_avant_e_tron_windows` | Audi A6 Avant e-tron Windows | unknown |  | window |  |
| `binary_sensor.bad_eg_fenster` | Bad EG Fenster | off |  | window |  |
| `binary_sensor.bad_eg_heating` | Bad EG heating | off |  |  |  |
| `binary_sensor.bad_og_fenster` | Bad OG Fenster | off |  | window |  |
| `binary_sensor.bad_og_lk1_dusche` | Bad OG LK1 (Dusche) | off |  | motion |  |
| `binary_sensor.bad_og_lk2_waschbecken` | Bad OG LK2 (Waschbecken) | unavailable |  | motion |  |
| `binary_sensor.bad_og_lk3_toilette` | Bad OG LK3 (Toilette) | unavailable |  | motion |  |
| `binary_sensor.bad_og_radiator_test_heizen_an_aus` | Bad OG Radiator test Heizen an/aus | on |  |  |  |
| `binary_sensor.bad_og_test_heizen_an_aus` | Bad OG test Heizen an/aus | on |  |  |  |
| `binary_sensor.buro_fenster` | Büro Fenster | off |  | window |  |
| `binary_sensor.buro_test_heizen_an_aus` | Büro test Heizen an/aus | on |  |  |  |
| `binary_sensor.busverkehrsuberschreitung` | Busverkehrsüberschreitung | off |  |  |  |
| `binary_sensor.c386d1df8bbc_unnamed_app_online` | c386d1df8bbc unnamed_app Online | off |  | connectivity |  |
| `binary_sensor.cam_engel_animal` | CAM_Engel Animal | off |  |  |  |
| `binary_sensor.cam_engel_motion` | CAM_Engel Motion | off |  | motion |  |
| `binary_sensor.cam_engel_person` | CAM_Engel Person | off |  |  |  |
| `binary_sensor.cam_engel_vehicle` | CAM_Engel Vehicle | off |  |  |  |
| `binary_sensor.cam_terrasse_animal` | CAM_Terrasse Animal | off |  |  |  |
| `binary_sensor.cam_terrasse_motion` | CAM_Terrasse Motion | off |  | motion |  |
| `binary_sensor.cam_terrasse_person` | CAM_Terrasse Person | off |  |  |  |
| `binary_sensor.cam_terrasse_vehicle` | CAM_Terrasse Vehicle | off |  |  |  |
| `binary_sensor.cooktop_connectivity` | Connectivity | unavailable |  | connectivity |  |
| `binary_sensor.devbox_192_168_0_51_jupyterlab_online` | devbox-192-168-0-51 jupyterlab Online | on |  | connectivity |  |
| `binary_sensor.devbox_192_168_0_51_pv_forecast_online` | devbox-192-168-0-51 pv_forecast Online | on |  | connectivity |  |
| `binary_sensor.dishwasher_connectivity` | Connectivity | unavailable |  | connectivity |  |
| `binary_sensor.dishwasher_door` | Dishwasher Door | unavailable |  | door |  |
| `binary_sensor.dishwasher_remote_control` | Remote control | unavailable |  |  |  |
| `binary_sensor.dishwasher_remote_start` | Remote start | unavailable |  |  |  |
| `binary_sensor.ds214_drive_1_below_min_remaining_life` | ds214 (Drive 1) Below min remaining life | off |  | safety |  |
| `binary_sensor.ds214_drive_1_exceeded_max_bad_sectors` | ds214 (Drive 1) Exceeded max bad sectors | off |  | safety |  |
| `binary_sensor.ds214_drive_2_below_min_remaining_life` | Below min remaining life | unavailable |  | safety |  |
| `binary_sensor.ds214_drive_2_exceeded_max_bad_sectors` | Exceeded max bad sectors | unavailable |  | safety |  |
| `binary_sensor.ds214_security_status` | ds214 Security status | off |  | safety |  |
| `binary_sensor.esszimmer_fenster_test_heizen_an_aus` | Esszimmer Fenster test Heizen an/aus | on |  |  |  |
| `binary_sensor.esszimmer_terassentur` | Esszimmer Terassentür | off |  | window |  |
| `binary_sensor.esszimmer_trager_test_heizen_an_aus` | Esszimmer Träger test Heizen an/aus | on |  |  |  |
| `binary_sensor.esszimmer_wohnzimmer_fenster` | Esszimmer/Wohnzimmer Fenster | off |  | window |  |
| `binary_sensor.gastebad_fenster` | Gästebad Fenster | off |  | window |  |
| `binary_sensor.gastezimmer_fenster` | Gästezimmer Fenster | off |  | window |  |
| `binary_sensor.haustur` | Haustür | on |  | window |  |
| `binary_sensor.heizanforderung_gesamt` | Heizanforderung gesamt | on |  |  |  |
| `binary_sensor.heizanforderung_links` | Heizanforderung links | on |  |  |  |
| `binary_sensor.heizanforderung_rechts` | Heizanforderung rechts | on |  |  |  |
| `binary_sensor.hennings_cg_iphone_focus` | Henning’s CG iphone Focus | off |  |  |  |
| `binary_sensor.hennings_iphone_focus` | Henning’s iPhone Focus | off |  |  |  |
| `binary_sensor.iphone8_focus` | iPhone8 Focus | off |  |  |  |
| `binary_sensor.iphone_13_cgp_focus` | iPhone 13 CGp Focus | off |  |  |  |
| `binary_sensor.keller_flur_treppe_v3_keller_treppe_pir` | keller_flur_treppe_v3 Keller Treppe PIR | off |  | motion |  |
| `binary_sensor.kuche_alle_fenster` | Küche alle Fenster | off |  | window |  |
| `binary_sensor.kuche_fenster_links` | Küche Fenster links | off |  | window |  |
| `binary_sensor.kuche_fenster_rechts` | Küche Fenster rechts | off |  | window |  |
| `binary_sensor.kuche_test_heizen_an_aus` | Küche test Heizen an/aus | on |  |  |  |
| `binary_sensor.pv_ai_forecast_pv_forecast_service` | PV AI Forecast PV Forecast Service | on |  | running |  |
| `binary_sensor.rudiger_mop_attached` | Mop attached | unavailable |  | connectivity |  |
| `binary_sensor.rudiger_water_box_attached` | Water box attached | unavailable |  | connectivity |  |
| `binary_sensor.schlafzimmer_fenster` | Schlafzimmer Fenster | off |  | window |  |
| `binary_sensor.schmohlchens_iphone_focus` | Schmöhlchens iPhone Focus | off |  |  |  |
| `binary_sensor.shelly_keller_flur_input_0_input` | Shelly_Keller_Flur Input 0 | off |  | power |  |
| `binary_sensor.shelly_keller_flur_switch_0_overheating` | Shelly_Keller_Flur switch_0 overheating | off |  | problem |  |
| `binary_sensor.shelly_keller_flur_switch_0_overpowering` | Shelly_Keller_Flur switch_0 overpowering | off |  | problem |  |
| `binary_sensor.shelly_keller_flur_switch_0_overvoltage` | Shelly_Keller_Flur switch_0 overvoltage | off |  | problem |  |
| `binary_sensor.shellyplus1pm_441793cfd99c_switch_0_overcurrent` | Shelly_Keller_Flur Overcurrent | off |  | problem |  |
| `binary_sensor.smart_ev_charging_service_status` | Smart EV Charging Service Status | on |  | connectivity |  |
| `binary_sensor.sport_fenster` | Sport Fenster | off |  | window |  |
| `binary_sensor.test` | test | off |  |  |  |
| `binary_sensor.washer_remote_start` | Washer Remote start | off |  |  |  |
| `binary_sensor.wohnzimmer_alle_fenster` | Wohnzimmer alle Fenster | off |  | window |  |
| `binary_sensor.wohnzimmer_esszimmer_kuche_gesamt` | Wohnzimmer/Esszimmer/Küche gesamt | off |  | window |  |
| `binary_sensor.wohnzimmer_fenster_hinten` | Wohnzimmer Fenster hinten | off |  | window |  |
| `binary_sensor.wohnzimmer_fenster_kamin` | Wohnzimmer Fenster Kamin | off |  | window |  |
| `binary_sensor.wohnzimmer_kamin_test_heizen_an_aus` | Wohnzimmer Kamin test Heizen an/aus | on |  |  |  |
| `binary_sensor.wohnzimmer_lk1_kuche` | Wohnzimmer LK1 (Küche) | off |  | motion |  |
| `binary_sensor.wohnzimmer_lk2_esszimmer` | Wohnzimmer LK2 (Esszimmer) | off |  | motion |  |
| `binary_sensor.wohnzimmer_lk3_wohnzimmer_eingang` | Wohnzimmer LK3 (Wohnzimmer / Eingang) | off |  | motion |  |
| `binary_sensor.wohnzimmer_test_heizen_an_aus` | Wohnzimmer test Heizen an/aus | unavailable |  |  |  |
| `binary_sensor.wohnzimmer_test_heizen_an_aus_2` | Wohnzimmer test Heizen an/aus | on |  |  |  |
| `binary_sensor.workday_sensor` | Workday Sensor | on |  |  |  |

### light

31 entities

| Entity ID | Name | State | Unit | Class | Area | Extra |
|-----------|------|-------|------|-------|------|-------|
| `light.abstellraum_deckenlicht` | Abstellraum Deckenlicht | off |  |  |  | supported_color_modes=[onoff] |
| `light.ankleide_deckenlicht` | Ankleide Deckenlicht | off |  |  |  | supported_color_modes=[onoff] |
| `light.aussen_1` | Außen 1 () | off |  |  |  | supported_color_modes=[onoff] |
| `light.aussen_2_terasse` | Außen 2 (Terasse) | on |  |  |  | supported_color_modes=[onoff] |
| `light.aussen_3_vorne` | Außen 3 (Vorne) | off |  |  |  | supported_color_modes=[onoff] |
| `light.aussen_4` | Außen 4 () | off |  |  |  | supported_color_modes=[onoff] |
| `light.aussen_5` | Außen 5 () | off |  |  |  | supported_color_modes=[onoff] |
| `light.bad_eg_deckenlicht` | Bad EG Deckenlicht | off |  |  |  | supported_color_modes=[onoff] |
| `light.bad_og_dusche_led_band` | Bad OG Dusche LED Band | off |  |  |  | supported_color_modes=[brightness] |
| `light.bad_og_duschlicht` | Bad OG Duschlicht | off |  |  |  | supported_color_modes=[onoff] |
| `light.bad_og_spiegel` | Bad OG Spiegel | on |  |  |  | supported_color_modes=[onoff] |
| `light.bad_og_spots` | Bad OG Spots | off |  |  |  | supported_color_modes=[brightness] |
| `light.buro_deckenlicht` | Büro Deckenlicht | off |  |  |  | supported_color_modes=[onoff] |
| `light.cam_engel_floodlight` | CAM_Engel Floodlight | off |  |  |  | supported_color_modes=[brightness] |
| `light.cam_engel_status_led` | CAM_Engel Status LED | on |  |  |  | supported_color_modes=[onoff] |
| `light.cam_terrasse_floodlight` | CAM_Terrasse Floodlight | off |  |  |  | supported_color_modes=[brightness] |
| `light.cam_terrasse_status_led` | CAM_Terrasse Status LED | on |  |  |  | supported_color_modes=[onoff] |
| `light.esszimmer_deckenlicht` | Esszimmer Deckenlicht | off |  |  |  | supported_color_modes=[brightness] |
| `light.flur_eg_sd_ecke` | Flur_EG_SD_ecke | off |  |  |  | supported_color_modes=[onoff] |
| `light.flur_eg_spots` | Flur EG Spots | off |  |  |  | supported_color_modes=[brightness] |
| `light.flur_og_hangelampe` | Flur_OG_Hängelampe | off |  |  |  | supported_color_modes=[brightness] |
| `light.flur_og_spots` | Flur OG Spots | off |  |  |  | supported_color_modes=[brightness] |
| `light.gaste_wc_spiegel` | Gäste WC Spiegel | off |  |  |  | supported_color_modes=[onoff] |
| `light.gastezimmer_deckenlicht` | Gästezimmer Deckenlicht | off |  |  |  | supported_color_modes=[onoff] |
| `light.kuche_aufbauspots` | Küche Aufbauspots | off |  |  |  | supported_color_modes=[brightness] |
| `light.kuche_einbauspots` | Küche Einbauspots | off |  |  |  | supported_color_modes=[brightness] |
| `light.kuche_led_band` | Küche_LED_Band | off |  |  |  | supported_color_modes=[onoff] |
| `light.schlafzimmer_deckenlicht` | Schlafzimmer Deckenlicht | off |  |  |  | supported_color_modes=[brightness] |
| `light.sportdeckenlicht` | Sport Deckenlicht | off |  |  |  | supported_color_modes=[onoff] |
| `light.wohnzimmer_sd_flurwand_rechts` | Wohnzimmer_SD_flurwand_rechts | off |  |  |  | supported_color_modes=[onoff] |
| `light.wohnzimmer_sd_sportwand_rechts` | Wohnzimmer_SD_sportwand_rechts | off |  |  |  | supported_color_modes=[onoff] |

### switch

61 entities

| Entity ID | Name | State | Unit | Class | Area |
|-----------|------|-------|------|-------|------|
| `switch.batteries_charge_from_grid` | Batteries Charge from grid | off |  |  | mechanical |
| `switch.inverter_inverter_on_off` | Inverter Inverter ON/OFF | on |  |  | mechanical |
| `switch.inverter_mppt_scanning` | Inverter MPPT scanning | on |  |  | mechanical |
| `switch.shelly3em_main` | shelly3em_main | on |  |  | mechanical |
| `switch.abstellraum_prasenz_sperrobjekt` | Abstellraum Präsenz Sperrobjekt | off |  |  |  |
| `switch.amtron_pause_charging` | AMTRON Pause Charging | on |  |  |  |
| `switch.ankleide_prasenz_sperrobjekt` | Ankleide Präsenz Sperrobjekt | off |  |  |  |
| `switch.bad_og_led_1` | Bad OG LED 1 | off |  |  |  |
| `switch.bad_og_led_2` | Bad OG LED 2 | off |  |  |  |
| `switch.bad_og_led_3` | Bad OG LED 3 | off |  |  |  |
| `switch.bad_og_led_4` | Bad OG LED 4 | off |  |  |  |
| `switch.bad_og_luftung` | Bad OG Lüftung | off |  |  |  |
| `switch.bad_og_prasenz_sperrobjekt` | Bad OG Präsenz Sperrobjekt | off |  |  |  |
| `switch.cam_engel_email_on_event` | CAM_Engel Email on event | on |  |  |  |
| `switch.cam_engel_ftp_upload` | CAM_Engel FTP upload | off |  |  |  |
| `switch.cam_engel_infrared_lights_in_night_mode` | CAM_Engel Infrared lights in night mode | on |  |  |  |
| `switch.cam_engel_push_notifications` | CAM_Engel Push notifications | on |  |  |  |
| `switch.cam_engel_record` | CAM_Engel Record | on |  |  |  |
| `switch.cam_engel_record_audio` | CAM_Engel Record audio | off |  |  |  |
| `switch.cam_engel_siren_on_event` | CAM_Engel Siren on event | off |  |  |  |
| `switch.cam_terrasse_email_on_event` | CAM_Terrasse Email on event | on |  |  |  |
| `switch.cam_terrasse_ftp_upload` | CAM_Terrasse FTP upload | off |  |  |  |
| `switch.cam_terrasse_infrared_lights_in_night_mode` | CAM_Terrasse Infrared lights in night mode | on |  |  |  |
| `switch.cam_terrasse_push_notifications` | CAM_Terrasse Push notifications | on |  |  |  |
| `switch.cam_terrasse_record` | CAM_Terrasse Record | on |  |  |  |
| `switch.cam_terrasse_record_audio` | CAM_Terrasse Record audio | off |  |  |  |
| `switch.cam_terrasse_siren_on_event` | CAM_Terrasse Siren on event | off |  |  |  |
| `switch.cooktop_child_lock` | Child lock | unavailable |  |  |  |
| `switch.cooktop_power` | Power | unavailable |  |  |  |
| `switch.dishwasher_extra_dry` | Extra dry | unavailable |  |  |  |
| `switch.dishwasher_intensive_zone` | Intensive zone | unavailable |  |  |  |
| `switch.dishwasher_power` | Power | unavailable |  |  |  |
| `switch.dishwasher_program_auto2` | Dishwasher Program Auto2 | unavailable |  |  |  |
| `switch.dishwasher_program_eco50` | Dishwasher Program Eco50 | unavailable |  |  |  |
| `switch.dishwasher_program_glas40` | Dishwasher Program Glas40 | unavailable |  |  |  |
| `switch.dishwasher_program_intensivpower` | Dishwasher Program IntensivPower | unavailable |  |  |  |
| `switch.dishwasher_program_kurz60` | Dishwasher Program Kurz60 | unavailable |  |  |  |
| `switch.dishwasher_program_machinecare` | Dishwasher Program MachineCare | unavailable |  |  |  |
| `switch.dishwasher_program_prerinse` | Dishwasher Program PreRinse | unavailable |  |  |  |
| `switch.dishwasher_vario_speed` | Vario speed + | unavailable |  |  |  |
| `switch.esszimmer_sds_wand_trager` | Esszimmer SDs Wand Träger | off |  |  |  |
| `switch.fake_scene_essen` | Essen - Scenenact. | off |  |  |  |
| `switch.fake_scene_kochen` | Kochen - Scenenact. | off |  |  |  |
| `switch.fake_scene_tv` | TV - Scenenact. | off |  |  |  |
| `switch.flur_eg_prasenz_sperrobjekt` | Flur EG Präsenz Sperrobjekt | off |  |  |  |
| `switch.flur_og_prasenz_sperrobjekt` | Flur OG Präsenz Sperrobjekt | off |  |  |  |
| `switch.gastebad_prasenz_sperrobjekt` | Gästebad Präsenz Sperrobjekt | off |  |  |  |
| `switch.keller_heizungspumpe` | Keller Heizungspumpe | on |  |  |  |
| `switch.keller_olraum_ventilator` | Keller Ölraum Ventilator | off |  |  |  |
| `switch.keller_zirkulationspumpe` | Keller Zirkulationspumpe | off |  |  |  |
| `switch.knx_badog_fake_scene_duschen` | Duschen - Scenenact | off |  |  |  |
| `switch.knx_badog_fake_scene_putzen` | Putzen Bad OG - Scenenact | off |  |  |  |
| `switch.kuche_sd_ipad` | Küche_SD_ipad | off |  |  |  |
| `switch.rudiger_do_not_disturb` | Do not disturb | unavailable |  |  |  |
| `switch.schlafzimmer_heizen_sperrobjekt` | Schlafzimmer heizen Sperrobjekt | off |  |  |  |
| `switch.shelly_keller_flur_switch_0` | Shelly_Keller_Flur switch_0 | off |  |  |  |
| `switch.tag_nacht_auto` | Tag/Nacht auto | off |  |  |  |
| `switch.tag_nacht_manu` | Tag/Nacht manu | off |  |  |  |
| `switch.waschkeller_luftung` | Waschkeller Lüftung | off |  |  |  |
| `switch.washer_power` | Washer Power | off |  | switch |  |
| `switch.wohnzimmer_prasenz_sperrobjekt` | Wohnzimmer Präsenz Sperrobjekt gesamt | off |  |  |  |

### climate

13 entities

| Entity ID | Name | State | Unit | Class | Area | Extra |
|-----------|------|-------|------|-------|------|-------|
| `climate.ankleide` | Ankleide | heat |  |  |  | hvac_modes=[heat]; min_temp=9.0; max_temp=21.0 |
| `climate.bad_eg` | Bad EG | heat |  |  |  | hvac_modes=[heat]; min_temp=1.0; max_temp=13.0 |
| `climate.bad_og` | Bad OG | heat |  |  |  | hvac_modes=[heat]; min_temp=13.0; max_temp=25.0 |
| `climate.bad_og_heizung_2` | Bad OG Heizung | heat |  |  |  | hvac_modes=[heat]; min_temp=13.0; max_temp=25.0 |
| `climate.buro` | Büro | heat |  |  |  | hvac_modes=[heat]; min_temp=12.4; max_temp=24.4 |
| `climate.flur_eg` | Flur EG | heat |  |  |  | hvac_modes=[heat]; min_temp=10.5; max_temp=22.5 |
| `climate.flur_og` | Flur OG | heat |  |  |  | hvac_modes=[heat]; min_temp=10.0; max_temp=22.0 |
| `climate.gastebad_2` | Gästebad | heat |  |  |  | hvac_modes=[heat]; min_temp=8.0; max_temp=20.0 |
| `climate.gastebad_t` | Gästebad | unavailable |  |  |  | hvac_modes=[heat]; min_temp=10.0; max_temp=22.0 |
| `climate.gastezimmer` | Gästezimmer | heat |  |  |  | hvac_modes=[heat]; min_temp=1.0; max_temp=13.0 |
| `climate.schlafzimmer` | Schlafzimmer | heat |  |  |  | hvac_modes=[heat]; min_temp=9.0; max_temp=21.0 |
| `climate.sport` | Sport | heat |  |  |  | hvac_modes=[heat]; min_temp=1.0; max_temp=13.0 |
| `climate.wohnzimmer_2` | Wohnzimmer | heat |  |  |  | hvac_modes=[heat]; min_temp=7.0; max_temp=32.0 |

### cover

14 entities

| Entity ID | Name | State | Unit | Class | Area | Extra |
|-----------|------|-------|------|-------|------|-------|
| `cover.ankleide_shutter` | Ankleide shutter | open |  |  |  | current_position=100 |
| `cover.bad_eg_shutter` | Bad EG shutter | open |  |  |  | current_position=23 |
| `cover.bad_og_shutter` | Bad OG shutter | open |  |  |  | current_position=100 |
| `cover.buro_shutter` | Büro shutter | open |  |  |  | current_position=100 |
| `cover.esszimmer_gr_fenster_shutter_2` | Esszimmer gr Fenster shutter | open |  |  |  | current_position=100 |
| `cover.esszimmer_terassentur_shutter_2` | Esszimmer Terassentür shutter | open |  |  |  | current_position=100 |
| `cover.gastebad_shutter` | Gästebad shutter | open |  |  |  | current_position=100 |
| `cover.gastezimmer_shutter` | Gästezimmer shutter | open |  |  |  | current_position=100 |
| `cover.kuche_shutter` | Küche shutter | open |  |  |  | current_position=100 |
| `cover.markise_shutter` | Markise shutter | closed |  |  |  | current_position=0 |
| `cover.schlafzimmer_shutter` | Schlafzimmer shutter | open |  |  |  | current_position=100 |
| `cover.sport_shutter` | Sport shutter | open |  |  |  | current_position=100 |
| `cover.wohnzimmer_fenster_links_shutter` | Wohnzimmer Fenster links shutter | open |  |  |  | current_position=100 |
| `cover.wohnzimmer_fenster_rechts_kamin_shutter` | Wohnzimmer FEnster rechts Kamin shutter | open |  |  |  | current_position=100 |

### media_player

3 entities

| Entity ID | Name | State | Unit | Class | Area | Extra |
|-----------|------|-------|------|-------|------|-------|
| `media_player.kuche` | Küche | idle |  |  | Küche |  |
| `media_player.lg_tv` | LG TV | off |  | tv | Living Room | source_list=[ARD Mediathek, Art Gallery, Home Dashboard, Live TV, Prime Video, … |
| `media_player.rx_v473_92d3e3` | RX-V473 92D3E3 | idle |  |  |  |  |

### camera

2 entities

| Entity ID | Name | State | Unit | Class | Area |
|-----------|------|-------|------|-------|------|
| `camera.cam_engel_fluent` | CAM_Engel Fluent | idle |  |  |  |
| `camera.cam_terrasse_fluent` | CAM_Terrasse Fluent | idle |  |  |  |

### vacuum

1 entities

| Entity ID | Name | State | Unit | Class | Area |
|-----------|------|-------|------|-------|------|
| `vacuum.rudiger` |  | unavailable |  |  |  |

### automation

9 entities

| Entity ID | Name | State | Unit | Class | Area |
|-----------|------|-------|------|-------|------|
| `automation.henning_enter_nb9` | Henning_enter_NB9 | unavailable |  |  |  |
| `automation.henning_leave_home` | Henning_leave_home | unavailable |  |  |  |
| `automation.set_tag_nacht_manu_11_30pm` | set tag/nacht manu 11:30pm | on |  |  |  |
| `automation.set_tag_nacht_manu_to_day_weekday` | set tag nacht manu to DAY weekday | on |  |  |  |
| `automation.sun_protection_forecast_temp_sun_altitude_south` | Sun Protection - Forecast Temp & Sun Altitude - South | on |  |  |  |
| `automation.sun_protection_forecast_temp_sun_altitude_west` | Sun Protection - Forecast Temp & Sun Altitude - West | on |  |  |  |
| `automation.tag_nacht_auto_9pm` | Tag/Nacht auto (sunrise, sunset) | on |  |  |  |
| `automation.tag_nacht_manu_weekend_am` | Tag/Nacht manu weekend AM | on |  |  |  |
| `automation.wohnzimmer_climate_7am` | Wohnzimmer_Climate_7am | unavailable |  |  |  |

### script

4 entities

| Entity ID | Name | State | Unit | Class | Area |
|-----------|------|-------|------|-------|------|
| `script.bad_og_handle_vent` | Bad_OG_Handle_Vent | off |  |  |  |
| `script.bad_og_light_handle` | Bad_OG_Light_Handle | off |  |  |  |
| `script.temperatures` | Temperatures | off |  |  |  |
| `script.zirkulationspumpe_handle` | Zirkulationspumpe_handle | off |  |  |  |

### scene

7 entities

| Entity ID | Name | State | Unit | Class | Area |
|-----------|------|-------|------|-------|------|
| `scene.bad_og` | Bad OG (tag) | 2026-02-11T08:19:55.689047+00:00 |  |  |  |
| `scene.bad_og_nacht` | Bad OG (Nacht) | 2026-02-10T22:50:44.676738+00:00 |  |  |  |
| `scene.duschen` | Duschen | 2026-02-10T18:11:32.700153+00:00 |  |  |  |
| `scene.essen` | Essen | 2026-02-10T18:47:13.911755+00:00 |  |  |  |
| `scene.kochen` | Kochen | 2026-02-10T16:32:21.508841+00:00 |  |  |  |
| `scene.party` | party | 2025-06-08T14:27:45.596657+00:00 |  |  |  |
| `scene.tv` | TV | 2026-02-10T19:44:16.489701+00:00 |  |  |  |

### input_boolean

18 entities

| Entity ID | Name | State | Unit | Class | Area |
|-----------|------|-------|------|-------|------|
| `input_boolean.cover_manage_cover_with_sun` | cover_manage_cover_with_sun | off |  |  |  |
| `input_boolean.ev_full_by_morning` | EV Full by Morning | off |  |  |  |
| `input_boolean.heating_manual` | heating_manual | on |  |  |  |
| `input_boolean.heating_period` | heating_period | off |  |  |  |
| `input_boolean.homeoffice` | Homeoffice | off |  |  |  |
| `input_boolean.knx_wohnzimmer_toggle_essen` | knx_wohnzimmer_toggle_essen | off |  |  |  |
| `input_boolean.knx_wohnzimmer_toggle_kochen` | knx_wohnzimmer_toggle_kochen | off |  |  |  |
| `input_boolean.knx_wohnzimmer_toggle_tv` | knx_wohnzimmer_toggle_tv | off |  |  |  |
| `input_boolean.party_mode` | party_mode | off |  |  |  |
| `input_boolean.presence_home` | presence_home | on |  |  |  |
| `input_boolean.schlafzimmer_unter_15` | schlafzimmer_unter_15 | off |  |  |  |
| `input_boolean.short_trip` | Kurztrip | off |  |  |  |
| `input_boolean.sperrobjekt_bad_og_luefter` | sperrobjekt_bad_og_luefter | off |  |  |  |
| `input_boolean.sun_protection_forecast_temp_sun_altitude_south_active` | sun_protection_forecast_temp_sun_altitude_south_active | off |  |  |  |
| `input_boolean.sun_protection_forecast_temp_sun_altitude_west_active` | sun_protection_forecast_temp_sun_altitude_west_active | off |  |  |  |
| `input_boolean.unterwegs` | Unterwegs | off |  |  |  |
| `input_boolean.urlaub_und_zuhaus` | urlaub_und_zuhaus | off |  |  |  |
| `input_boolean.vacation` | Vacation | off |  |  |  |

### input_number

5 entities

| Entity ID | Name | State | Unit | Class | Area | Extra |
|-----------|------|-------|------|-------|------|-------|
| `input_number.ev_battery_capacity_kwh` | EV Battery Capacity | 86.0 | kWh |  |  | min=10.0; max=150.0; step=1.0; mode=slider |
| `input_number.ev_target_energy_kwh` | EV Target Energy | 86.0 | kWh |  |  | min=0.0; max=100.0; step=1.0; mode=slider |
| `input_number.price_per_kwh_electricity_grid` | price_per_kwh_electricity_grid | 26.11 | cent/kWh |  |  | min=25.0; max=50.0; step=1.0; mode=box |
| `input_number.price_per_kwh_electricity_pv` | price_per_kwh_electricity_pv | 7.23 | cent/kWh |  |  | min=0.0; max=15.0; step=1.0; mode=box |
| `input_number.price_per_liter_oil` | price_per_liter_oil | 93.0 | cent/liter |  |  | min=80.0; max=200.0; step=1.0; mode=box |

### input_select

1 entities

| Entity ID | Name | State | Unit | Class | Area | Extra |
|-----------|------|-------|------|-------|------|-------|
| `input_select.ev_charge_mode` | EV Charge Mode | Smart |  |  |  | options=[Off, PV Surplus, Smart, Eco, Fast, Manual] |

### input_datetime

1 entities

| Entity ID | Name | State | Unit | Class | Area |
|-----------|------|-------|------|-------|------|
| `input_datetime.ev_departure_time` | EV Departure Time | 07:00:00 |  |  |  |

### number

35 entities

| Entity ID | Name | State | Unit | Class | Area | Extra |
|-----------|------|-------|------|-------|------|-------|
| `number.batteries_backup_power_soc` | Batteries Backup power SOC | 0.0 | % |  | mechanical | min=0.0; max=100; step=0.1; mode=box |
| `number.batteries_end_of_charge_soc` | Batteries End-of-charge SOC | 100.0 | % |  | mechanical | min=90; max=100; step=0.1; mode=box |
| `number.batteries_end_of_discharge_soc` | Batteries End-of-discharge SOC | 5.0 | % |  | mechanical | min=0.0; max=20; step=0.1; mode=box |
| `number.batteries_grid_charge_cutoff_soc` | Batteries Grid charge cutoff SOC | 100.0 | % |  | mechanical | min=20; max=100; step=0.1; mode=box |
| `number.batteries_grid_charge_maximum_power` | Batteries Grid charge maximum power | 15000 | W |  | mechanical | min=0.0; max=15000; step=1.0; mode=box |
| `number.batteries_maximum_charging_power` | Batteries Maximum charging power | 3500 | W |  | mechanical | min=0.0; max=3500; step=1.0; mode=box |
| `number.batteries_maximum_discharging_power` | Batteries Maximum discharging power | 3500 | W |  | mechanical | min=0.0; max=3500; step=1.0; mode=box |
| `number.batteries_peak_shaving_soc` | Batteries Peak Shaving SOC | 50.0 | % |  | mechanical | min=5.0; max=100; step=0.1; mode=box |
| `number.inverter_mppt_scan_interval` | Inverter MPPT scan interval | 5 | minutes |  | mechanical | min=5; max=30; step=1; mode=box |
| `number.inverter_power_derating` | Inverter Power derating | 0 | W |  | mechanical | min=0.0; max=22000; step=1; mode=box |
| `number.inverter_power_derating_by_percentage` | Inverter Power derating (by percentage) | 100.0 | % |  | mechanical | min=-100; max=100; step=0.1; mode=box |
| `number.amtron_communication_timeout_s` | AMTRON Communication Timeout [s] | 360.0 |  |  |  | min=0.0; max=600.0; step=5.0; mode=auto |
| `number.amtron_hems_current_limit_a` | AMTRON HEMS Current Limit [A] | 0.0 |  |  |  | min=0.0; max=32.0; step=0.1; mode=auto |
| `number.amtron_hems_power_limit_w` | AMTRON HEMS Power Limit [W] | 0.0 |  |  |  | min=0.0; max=11000.0; step=60.0; mode=auto |
| `number.amtron_power_limit_w` | AMTRON power limit (W) | unknown |  |  |  | min=0.0; max=22000.0; step=10.0; mode=auto |
| `number.amtron_safe_current_a` | AMTRON Safe Current [A] | 6.0 |  |  |  | min=0.0; max=32.0; step=1.0; mode=auto |
| `number.bad_og_test_heizen_ubersteuerung_max_ventilstellwert` | Bad OG test Heizen Übersteuerung Max Ventilstellwert | 0 | % |  |  | min=0; max=100; step=1; mode=auto |
| `number.bad_og_test_heizen_ubersteuerung_min_ventilstellwert` | Bad OG test Heizen Übersteuerung Min Ventilstellwert | 0 | % |  |  | min=0; max=100; step=1; mode=auto |
| `number.buro_test_heizen_ubersteuerung_max_ventilstellwert` | Büro test Heizen Übersteuerung Max Ventilstellwert | 0 | % |  |  | min=0; max=100; step=1; mode=auto |
| `number.buro_test_heizen_ubersteuerung_min_ventilstellwert` | Büro test Heizen Übersteuerung Min Ventilstellwert | 0 | % |  |  | min=0; max=100; step=1; mode=auto |
| `number.cam_engel_ai_animal_sensitivity` | CAM_Engel AI animal sensitivity | 60 |  |  |  | min=0; max=100; step=1; mode=auto |
| `number.cam_engel_ai_person_sensitivity` | CAM_Engel AI person sensitivity | 60 |  |  |  | min=0; max=100; step=1; mode=auto |
| `number.cam_engel_ai_vehicle_sensitivity` | CAM_Engel AI vehicle sensitivity | 60 |  |  |  | min=0; max=100; step=1; mode=auto |
| `number.cam_engel_motion_sensitivity` | CAM_Engel Motion sensitivity | 41 |  |  |  | min=1; max=50; step=1; mode=auto |
| `number.cam_engel_volume` | CAM_Engel Volume | 100 |  |  |  | min=0; max=100; step=1; mode=auto |
| `number.cam_terrasse_ai_animal_sensitivity` | CAM_Terrasse AI animal sensitivity | 60 |  |  |  | min=0; max=100; step=1; mode=auto |
| `number.cam_terrasse_ai_person_sensitivity` | CAM_Terrasse AI person sensitivity | 60 |  |  |  | min=0; max=100; step=1; mode=auto |
| `number.cam_terrasse_ai_vehicle_sensitivity` | CAM_Terrasse AI vehicle sensitivity | 60 |  |  |  | min=0; max=100; step=1; mode=auto |
| `number.cam_terrasse_motion_sensitivity` | CAM_Terrasse Motion sensitivity | 41 |  |  |  | min=1; max=50; step=1; mode=auto |
| `number.cam_terrasse_volume` | CAM_Terrasse Volume | 100 |  |  |  | min=0; max=100; step=1; mode=auto |
| `number.dishwasher_start_in_relative` | Start in relative | unavailable | s |  |  | min=0.0; max=86400; step=1.0; mode=auto |
| `number.rudiger_volume` | Volume | unavailable | % |  |  | min=0; max=100; step=1.0; mode=auto |
| `number.washer_delay_ends_in` | Washer Delayed end | 0 | h |  |  | min=0; max=19; step=1; mode=box |
| `number.wohnzimmer_test_heizen_ubersteuerung_max_ventilstellwert` | Wohnzimmer test Heizen Übersteuerung Max Ventilstellwert | 0 | % |  |  | min=0; max=100; step=1; mode=auto |
| `number.wohnzimmer_test_heizen_ubersteuerung_min_ventilstellwert` | Wohnzimmer test Heizen Übersteuerung Min Ventilstellwert | 0 | % |  |  | min=0; max=100; step=1; mode=auto |

### select

12 entities

| Entity ID | Name | State | Unit | Class | Area | Extra |
|-----------|------|-------|------|-------|------|-------|
| `select.batteries_capacity_control_mode` | Batteries Capacity Control Mode | unavailable |  |  | mechanical | options=[disable, active_capacity_control, apparent_power_limit] |
| `select.batteries_excess_pv_energy_use_in_tou` | Batteries Excess PV energy use in TOU | fed_to_grid |  |  | mechanical | options=[fed_to_grid, charge] |
| `select.batteries_working_mode` | Batteries Working Mode | maximise_self_consumption |  |  | mechanical | options=[adaptive, fixed_charge_discharge, maximise_self_consumption, fully_fed… |
| `select.cam_engel_day_night_mode` | CAM_Engel Day night mode | auto |  |  |  | options=[auto, color, blackwhite] |
| `select.cam_engel_floodlight_mode` | CAM_Engel Floodlight mode | auto |  |  |  | options=[off, auto, schedule] |
| `select.cam_terrasse_day_night_mode` | CAM_Terrasse Day night mode | auto |  |  |  | options=[auto, color, blackwhite] |
| `select.cam_terrasse_floodlight_mode` | CAM_Terrasse Floodlight mode | auto |  |  |  | options=[off, auto, schedule] |
| `select.dishwasher_active_program` | Active program | unavailable |  |  |  | options=[dishcare_dishwasher_program_auto_2, dishcare_dishwasher_program_eco_50… |
| `select.dishwasher_selected_program` | Selected program | unavailable |  |  |  | options=[dishcare_dishwasher_program_auto_2, dishcare_dishwasher_program_eco_50… |
| `select.rudiger_mop_intensity` | Mop intensity | unavailable |  |  |  | options=[off, low, medium, high, custom] |
| `select.rudiger_mop_mode` | Mop mode | unavailable |  |  |  | options=[standard, deep, deep_plus, custom] |
| `select.washer_operation` | Washer Operation | unknown |  |  |  | options=[start, stop, power_off, wake_up] |

### button

6 entities

| Entity ID | Name | State | Unit | Class | Area |
|-----------|------|-------|------|-------|------|
| `button.gaestewc_esp32_esp32_guest_wc_restart` | gaesteWC-esp32 ESP32 Guest WC Restart | unavailable |  | restart | guest_WC |
| `button.shelly3em_main_reboot` | shelly3em_main Reboot | unknown |  | restart | mechanical |
| `button.dishwasher_stop_program` | Stop program | unavailable |  |  |  |
| `button.ds214_reboot` | ds214 Reboot | unknown |  | restart |  |
| `button.ds214_shutdown` | ds214 Shutdown | unknown |  |  |  |
| `button.shelly_keller_flur_reboot` | Shelly_Keller_Flur Reboot | unknown |  | restart |  |

### device_tracker

9 entities

| Entity ID | Name | State | Unit | Class | Area |
|-----------|------|-------|------|-------|------|
| `device_tracker.hennings_cg_iphone` | Henning’s CG iphone | not_home |  |  |  |
| `device_tracker.hennings_iphone` | Henning’s iPhone | home |  |  |  |
| `device_tracker.iphone` | iPhone | not_home |  |  |  |
| `device_tracker.iphone16_hp_hs` | iPhone16 HP HS | home |  |  |  |
| `device_tracker.iphone8` | iPhone8 | home |  |  |  |
| `device_tracker.iphone_13_cgp` | iPhone 13 CGp | home |  |  |  |
| `device_tracker.iphone_2` | iPhone | unknown |  |  |  |
| `device_tracker.redminote13` | redminote13 | home |  |  |  |
| `device_tracker.schmohlchens_iphone` | Schmöhlchens iPhone | home |  |  |  |

### person

2 entities

| Entity ID | Name | State | Unit | Class | Area |
|-----------|------|-------|------|-------|------|
| `person.henning_schuttken` | Henning Schüttken | home |  |  |  |
| `person.nicole_schuttken` | Nicole Schüttken | home |  |  |  |

### zone

5 entities

| Entity ID | Name | State | Unit | Class | Area |
|-----------|------|-------|------|-------|------|
| `zone.b_k_work` | B+K_work | 0 |  |  |  |
| `zone.coming_home` | coming_home | 0 |  |  |  |
| `zone.home` | Home | 2 |  |  |  |
| `zone.mama` | mama | 0 |  |  |  |
| `zone.work_parking` | work_parking | 0 |  |  |  |

### sun

1 entities

| Entity ID | Name | State | Unit | Class | Area |
|-----------|------|-------|------|-------|------|
| `sun.sun` | Sun | above_horizon |  |  |  |

### weather

4 entities

| Entity ID | Name | State | Unit | Class | Area |
|-----------|------|-------|------|-------|------|
| `weather.forecast_home` | Home | unavailable |  |  |  |
| `weather.forecast_home_2` | Forecast Home | rainy |  |  |  |
| `weather.home` | Home | rainy |  |  |  |
| `weather.openweathermap` | OpenWeatherMap | rainy |  |  |  |

### update

25 entities

| Entity ID | Name | State | Unit | Class | Area |
|-----------|------|-------|------|-------|------|
| `update.shelly3em_main_firmware_update` | shelly3em_main Firmware | off |  | firmware | mechanical |
| `update.audi_connect_update` | Audi connect update | off |  |  |  |
| `update.battery_sim_update` | Battery Simulator update | off |  |  |  |
| `update.cam_engel_firmware` | CAM_Engel Firmware | off |  | firmware |  |
| `update.cam_terrasse_firmware` | CAM_Terrasse Firmware | off |  | firmware |  |
| `update.ds214_dsm_update` | ds214 DSM update | on |  |  |  |
| `update.epex_spot_update` | EPEX Spot update | on |  |  |  |
| `update.esphome_update` | ESPHome Device Builder Update | on |  |  |  |
| `update.get_hacs_update` | Get HACS Update | off |  |  |  |
| `update.hacs_update` | HACS update | off |  |  |  |
| `update.home_assistant_core_update` | Home Assistant Core Update | on |  |  |  |
| `update.home_assistant_operating_system_update` | Home Assistant Operating System Update | on |  |  |  |
| `update.home_assistant_supervisor_update` | Home Assistant Supervisor Update | off |  |  |  |
| `update.huawei_solar_update` | Huawei Solar update | off |  |  |  |
| `update.keller_flur_treppe_v3_firmware` | Firmware | unavailable |  | firmware |  |
| `update.node_red_companion_update` | Node-RED Companion update | on |  |  |  |
| `update.node_red_update` | Node-RED Update | off |  |  |  |
| `update.pyscript_update` | pyscript update | on |  |  |  |
| `update.shelly_keller_flur_firmware_update` | Shelly_Keller_Flur firmware update | on |  | firmware |  |
| `update.smartthinq_lge_sensors_update` | SmartThinQ LGE Sensors update | unavailable |  |  |  |
| `update.studio_code_server_update` | Studio Code Server Update | on |  |  |  |
| `update.terminal_ssh_update` | Terminal & SSH Update | on |  |  |  |
| `update.thermal_comfort_update` | Thermal Comfort update | unavailable |  |  |  |
| `update.variable_update` | Variable update | unavailable |  |  |  |
| `update.watchman_update` | Watchman update | on |  |  |  |

### calendar

2 entities

| Entity ID | Name | State | Unit | Class | Area |
|-----------|------|-------|------|-------|------|
| `calendar.henning_cal` | henning_cal | off |  |  |  |
| `calendar.workday_sensor_calendar` | Workday Sensor Calendar | off |  |  |  |

### conversation

1 entities

| Entity ID | Name | State | Unit | Class | Area |
|-----------|------|-------|------|-------|------|
| `conversation.home_assistant` | Home Assistant | unknown |  |  |  |

### event

3 entities

| Entity ID | Name | State | Unit | Class | Area |
|-----------|------|-------|------|-------|------|
| `event.backup_automatic_backup` | Backup Automatic backup | 2026-02-09T03:34:52.476+00:00 |  |  |  |
| `event.washer_error` | Washer Error | unknown |  |  |  |
| `event.washer_notification` | Washer Notification | 2026-01-09T12:26:05.840+00:00 |  |  |  |

### remote

1 entities

| Entity ID | Name | State | Unit | Class | Area |
|-----------|------|-------|------|-------|------|
| `remote.kuche` | Küche | on |  |  | Küche |

### siren

2 entities

| Entity ID | Name | State | Unit | Class | Area |
|-----------|------|-------|------|-------|------|
| `siren.cam_engel_siren` | CAM_Engel Siren | unknown |  |  |  |
| `siren.cam_terrasse_siren` | CAM_Terrasse Siren | unknown |  |  |  |

### time

3 entities

| Entity ID | Name | State | Unit | Class | Area |
|-----------|------|-------|------|-------|------|
| `time.cooktop_alarm_clock` | Alarm clock | unavailable |  |  |  |
| `time.rudiger_do_not_disturb_begin` | Do not disturb begin | unavailable |  |  |  |
| `time.rudiger_do_not_disturb_end` | Do not disturb end | unavailable |  |  |  |

## Available Services

### audiconnect

6 services

#### `audiconnect.execute_vehicle_action`
**Execute Vehicle Action**

Performs various actions on the vehicle.

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| action | The specific action to perform on the vehicle. Note that av… | yes | select [lock, unlock, start_climatisation, stop_climatisation, start_charger, start_timed_charger (+5)] |
| vin | The Vehicle Identification Number (VIN) of the Audi vehicle… | yes | text |

#### `audiconnect.refresh_cloud_data`
**Refresh Cloud Data**

Retrieves current cloud data without triggering a vehicle refresh. Data may be outdated if the vehicle has not checked in recently.

*No fields*

#### `audiconnect.refresh_vehicle_data`
**Refresh Vehicle Data**

Requests an update of the vehicle state directly, as opposed to the normal update mechanism which only retrieves data from the cloud.

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| vin | The Vehicle Identification Number (VIN) of the Audi vehicle… | yes | text |

#### `audiconnect.set_target_soc`
**Set Target State of Charge**

Set the target state of charge (battery %) for the vehicle.

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| target_soc | Target state of charge percentage (20-100%). | yes | number (min=20.0, max=100.0, step=5.0, %) |
| vin | The Vehicle Identification Number (VIN) of the Audi vehicle… | yes | text |

#### `audiconnect.start_auxiliary_heating`
**Start Auxiliary Heating**

Start auxiliary heating the vehicle, with option for duration.

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| duration | The number of minutes the auxiliary heater should run befor… |  | number (min=10.0, max=60.0, step=10.0, minutes) |
| vin | The Vehicle Identification Number (VIN) of the Audi vehicle… | yes | text |

#### `audiconnect.start_climate_control`
**Start Climate Control**

Start the climate control with options for temperature, glass surface heating, and auto seat comfort.

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| climatisation_at_unlock | (Optional) Enable climate control to continue when vehicle … |  | boolean |
| climatisation_mode | (Optional) Maximum comfort (Comfort) or energy-saving (Econ… |  | select [comfort, economy] |
| glass_heating | (Optional) Enable or disable glass surface heating. |  | boolean |
| seat_fl | (Optional) Enable or disable Auto Seat Comfort for the fron… |  | boolean |
| seat_fr | (Optional) Enable or disable Auto Seat Comfort for the fron… |  | boolean |
| seat_rl | (Optional) Enable or disable Auto Seat Comfort for the rear… |  | boolean |
| seat_rr | (Optional) Enable or disable Auto Seat Comfort for the rear… |  | boolean |
| temp_c | (Optional) Set temperature in °C. Defaults to 21°C if not p… |  | number (min=15.0, max=30.0, step=1.0) |
| temp_f | (Optional) Set temperature in °F. Defaults to 70°F if not p… |  | number (min=59.0, max=85.0, step=1.0) |
| vin | The Vehicle Identification Number (VIN) of the Audi vehicle… | yes | text |

### automation

5 services

#### `automation.reload`
**Reload**

Reloads the automation configuration.

*No fields*

#### `automation.toggle`
**Toggle**

Toggles (enable / disable) an automation.

**Target**: entity: automation

*No fields*

#### `automation.trigger`
**Trigger**

Triggers the actions of an automation.

**Target**: entity: automation

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| skip_condition | Defines whether or not the conditions will be skipped. |  | boolean |

#### `automation.turn_off`
**Turn off**

Disables an automation.

**Target**: entity: automation

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| stop_actions | Stops currently running actions. |  | boolean |

#### `automation.turn_on`
**Turn on**

Enables an automation.

**Target**: entity: automation

*No fields*

### backup

1 services

#### `backup.create_automatic`
**Create automatic backup**

Creates a new backup with automatic backup settings.

*No fields*

### button

1 services

#### `button.press`
**Press**

Presses a button entity.

**Target**: entity: button

*No fields*

### calendar

2 services

#### `calendar.create_event`
**Create event**

Adds a new calendar event.

**Target**: entity: calendar

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| description | A more complete description of the event than the one provi… |  | text |
| end_date | The date the all-day event should end (exclusive). |  | date |
| end_date_time | The date and time the event should end. |  | datetime |
| in | Days or weeks that you want to create the event in. |  |  |
| location | The location of the event. |  | text |
| start_date | The date the all-day event should start. |  | date |
| start_date_time | The date and time the event should start. |  | datetime |
| summary | Defines the short summary or subject for the event. | yes | text |

#### `calendar.get_events`
**Get events**

Retrieves events on a calendar within a time range.

**Target**: entity: calendar

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| duration | Returns active events from Start time for the specified dur… |  | duration |
| end_date_time | Returns active events before this time (exclusive). Cannot … |  | datetime |
| start_date_time | Returns active events after this time (exclusive). When not… |  | datetime |

### camera

7 services

#### `camera.disable_motion_detection`
**Disable motion detection**

Disables the motion detection.

**Target**: entity: camera

*No fields*

#### `camera.enable_motion_detection`
**Enable motion detection**

Enables the motion detection.

**Target**: entity: camera

*No fields*

#### `camera.play_stream`
**Play stream**

Plays the camera stream on a supported media player.

**Target**: entity: camera

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| format | Stream format supported by the media player. |  | select [hls] |
| media_player | Media players to stream to. | yes | entity (media_player) |

#### `camera.record`
**Record**

Creates a recording of a live camera feed.

**Target**: entity: camera

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| duration | Planned duration of the recording. The actual duration may … |  | number (min=1.0, max=3600.0, step=1.0, seconds) |
| filename | Full path to filename. Must be mp4. | yes | text |
| lookback | Planned lookback period to include in the recording (in add… |  | number (min=0.0, max=300.0, step=1.0, seconds) |

#### `camera.snapshot`
**Take snapshot**

Takes a snapshot from a camera.

**Target**: entity: camera

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| filename | Full path to filename. | yes | text |

#### `camera.turn_off`
**Turn off**

Turns off the camera.

**Target**: entity: camera

*No fields*

#### `camera.turn_on`
**Turn on**

Turns on the camera.

**Target**: entity: camera

*No fields*

### climate

10 services

#### `climate.set_fan_mode`
**Set fan mode**

Sets fan operation mode.

**Target**: entity: climate

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| fan_mode | Fan operation mode. | yes | text |

#### `climate.set_humidity`
**Set target humidity**

Sets target humidity.

**Target**: entity: climate

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| humidity | Target humidity. | yes | number (min=30.0, max=99.0, step=1.0, %) |

#### `climate.set_hvac_mode`
**Set HVAC mode**

Sets HVAC operation mode.

**Target**: entity: climate

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| hvac_mode | HVAC operation mode. |  | state |

#### `climate.set_preset_mode`
**Set preset mode**

Sets preset mode.

**Target**: entity: climate

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| preset_mode | Preset mode. | yes | text |

#### `climate.set_swing_horizontal_mode`
**Set horizontal swing mode**

Sets horizontal swing operation mode.

**Target**: entity: climate

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| swing_horizontal_mode | Horizontal swing operation mode. | yes | text |

#### `climate.set_swing_mode`
**Set swing mode**

Sets swing operation mode.

**Target**: entity: climate

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| swing_mode | Swing operation mode. | yes | text |

#### `climate.set_temperature`
**Set target temperature**

Sets the temperature setpoint.

**Target**: entity: climate

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| hvac_mode | HVAC operation mode. |  | select [off, auto, cool, dry, fan_only, heat_cool (+1)] |
| target_temp_high | The max temperature setpoint. |  | number (min=0.0, max=250.0, step=0.1) |
| target_temp_low | The min temperature setpoint. |  | number (min=0.0, max=250.0, step=0.1) |
| temperature | The temperature setpoint. |  | number (min=0.0, max=250.0, step=0.1) |

#### `climate.toggle`
**Toggle**

Toggles climate device, from on to off, or off to on.

**Target**: entity: climate

*No fields*

#### `climate.turn_off`
**Turn off**

Turns climate device off.

**Target**: entity: climate

*No fields*

#### `climate.turn_on`
**Turn on**

Turns climate device on.

**Target**: entity: climate

*No fields*

### cloud

2 services

#### `cloud.remote_connect`
**Enable remote access**

Makes the instance UI accessible from outside of the local network by enabling your Home Assistant Cloud connection.

*No fields*

#### `cloud.remote_disconnect`
**Disable remote access**

Disconnects the instance UI from Home Assistant Cloud. This disables access to it from outside your local network.

*No fields*

### conversation

2 services

#### `conversation.process`
**Process**

Launches a conversation from a transcribed text.

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| agent_id | Conversation agent to process your request. The conversatio… |  | conversation_agent |
| conversation_id | ID of the conversation, to be able to continue a previous c… |  | text |
| language | Language of text. Defaults to server language. |  | text |
| text | Transcribed text input. | yes | text |

#### `conversation.reload`
**Reload**

Reloads the intent configuration.

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| agent_id | Conversation agent to reload. |  | conversation_agent |
| language | Language to clear cached intents for. Defaults to server la… |  | text |

### counter

4 services

#### `counter.decrement`
**Decrement**

Decrements a counter by its step size.

**Target**: entity: counter

*No fields*

#### `counter.increment`
**Increment**

Increments a counter by its step size.

**Target**: entity: counter

*No fields*

#### `counter.reset`
**Reset**

Resets a counter to its initial value.

**Target**: entity: counter

*No fields*

#### `counter.set_value`
**Set**

Sets the counter to a specific value.

**Target**: entity: counter

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| value | The new counter value the entity should be set to. | yes | number (min=0.0, max=9.223372036854776e+18, step=1.0) |

### cover

10 services

#### `cover.close_cover`
**Close**

Closes a cover.

**Target**: entity: cover

*No fields*

#### `cover.close_cover_tilt`
**Close tilt**

Tilts a cover to close.

**Target**: entity: cover

*No fields*

#### `cover.open_cover`
**Open**

Opens a cover.

**Target**: entity: cover

*No fields*

#### `cover.open_cover_tilt`
**Open tilt**

Tilts a cover open.

**Target**: entity: cover

*No fields*

#### `cover.set_cover_position`
**Set position**

Moves a cover to a specific position.

**Target**: entity: cover

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| position | Target position. | yes | number (min=0.0, max=100.0, step=1.0, %) |

#### `cover.set_cover_tilt_position`
**Set tilt position**

Moves a cover tilt to a specific position.

**Target**: entity: cover

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| tilt_position | Target tilt positition. | yes | number (min=0.0, max=100.0, step=1.0, %) |

#### `cover.stop_cover`
**Stop**

Stops the cover movement.

**Target**: entity: cover

*No fields*

#### `cover.stop_cover_tilt`
**Stop tilt**

Stops a tilting cover movement.

**Target**: entity: cover

*No fields*

#### `cover.toggle`
**Toggle**

Toggles a cover open/closed.

**Target**: entity: cover

*No fields*

#### `cover.toggle_cover_tilt`
**Toggle tilt**

Toggles a cover tilt open/closed.

**Target**: entity: cover

*No fields*

### device_tracker

1 services

#### `device_tracker.see`
**See**

Manually update the records of a seen legacy device tracker in the known_devices.yaml file.

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| battery | Battery level of the device. |  | number (min=0.0, max=100.0, step=1.0, %) |
| dev_id | ID of the device (find the ID in `known_devices.yaml`). |  | text |
| gps | GPS coordinates where the device is located, specified by l… |  | object |
| gps_accuracy | Accuracy of the GPS coordinates. |  | number (min=0.0, step=1.0, m) |
| host_name | Hostname of the device. |  | text |
| location_name | Name of the location where the device is located. The optio… |  | text |
| mac | MAC address of the device. |  | text |

### epex_spot

3 services

#### `epex_spot.fetch_data`
**Fetch data from all services or a specific service.**

Fetch data now

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| device_id | An EPEX Spot service instance ID. In case you have multiple… |  | device |

#### `epex_spot.get_highest_price_interval`
**Get highest price interval**

Get the time interval during which the price is at its highest point.

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| device_id | An EPEX Spot service instance ID. In case you have multiple… |  | device |
| duration | Required duration to complete appliance. | yes | duration |
| earliest_start | Earliest time to start the appliance. If omitted, the curre… |  | time |
| earliest_start_post | Postponement of `Earliest Start Time` in days: 0 = today (d… |  | number (min=0.0, max=2.0, step=1.0, days) |
| latest_end | Latest time to end the appliance. If omitted, the end of th… |  | time |
| latest_end_post | Postponement of `Latest End Time` in days: 0 = today (defau… |  | number (min=0.0, max=2.0, step=1.0, days) |

#### `epex_spot.get_lowest_price_interval`
**Get lowest price interval**

Get the time interval during which the price is at its lowest point.

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| device_id | An EPEX Spot service instance ID. In case you have multiple… |  | device |
| duration | Required duration to complete appliance. | yes | duration |
| earliest_start | Earliest time to start the appliance. If omitted, the curre… |  | time |
| earliest_start_post | Postponement of `Earliest Start Time` in days: 0 = today (d… |  | number (min=0.0, max=2.0, step=1.0, days) |
| latest_end | Latest time to end the appliance. If omitted, the end of th… |  | time |
| latest_end_post | Postponement of `Latest End Time` in days: 0 = today (defau… |  | number (min=0.0, max=2.0, step=1.0, days) |

### fan

9 services

#### `fan.decrease_speed`
**Decrease speed**

Decreases the speed of a fan.

**Target**: entity: fan

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| percentage_step | Percentage step by which the speed should be decreased. |  | number (min=0.0, max=100.0, step=1.0, %) |

#### `fan.increase_speed`
**Increase speed**

Increases the speed of a fan.

**Target**: entity: fan

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| percentage_step | Percentage step by which the speed should be increased. |  | number (min=0.0, max=100.0, step=1.0, %) |

#### `fan.oscillate`
**Oscillate**

Controls the oscillation of a fan.

**Target**: entity: fan

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| oscillating | Turns oscillation on/off. | yes | boolean |

#### `fan.set_direction`
**Set direction**

Sets a fan's rotation direction.

**Target**: entity: fan

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| direction | Direction of the fan rotation. | yes | select [forward, reverse] |

#### `fan.set_percentage`
**Set speed**

Sets the speed of a fan.

**Target**: entity: fan

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| percentage | Speed of the fan. | yes | number (min=0.0, max=100.0, step=1.0, %) |

#### `fan.set_preset_mode`
**Set preset mode**

Sets preset fan mode.

**Target**: entity: fan

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| preset_mode | Preset fan mode. | yes | text |

#### `fan.toggle`
**Toggle**

Toggles a fan on/off.

**Target**: entity: fan

*No fields*

#### `fan.turn_off`
**Turn off**

Turns fan off.

**Target**: entity: fan

*No fields*

#### `fan.turn_on`
**Turn on**

Turns fan on.

**Target**: entity: fan

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| percentage | Speed of the fan. |  | number (min=0.0, max=100.0, step=1.0, %) |
| preset_mode | Preset fan mode. |  | text |

### ffmpeg

3 services

#### `ffmpeg.restart`
**Restart**

Sends a restart command to an FFmpeg-based sensor.

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| entity_id | Name of entity that will restart. Platform dependent. |  | entity (binary_sensor) |

#### `ffmpeg.start`
**Start**

Sends a start command to an FFmpeg-based sensor.

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| entity_id | Name of entity that will start. Platform dependent. |  | entity (binary_sensor) |

#### `ffmpeg.stop`
**Stop**

Sends a stop command to an FFmpeg-based sensor.

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| entity_id | Name of entity that will stop. Platform dependent. |  | entity (binary_sensor) |

### file

1 services

#### `file.read_file`
**Read file**

Reads a file and returns the contents.

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| file_encoding | Encoding of the file (JSON, YAML.) |  | select [JSON, YAML] |
| file_name | Name of the file to read. |  | text |

### frontend

2 services

#### `frontend.reload_themes`
**Reload themes**

Reloads themes from the YAML-configuration.

*No fields*

#### `frontend.set_theme`
**Set the default theme**

Sets the default theme Home Assistant uses. Can be overridden by a user.

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| mode | Theme mode. |  | select [dark, light] |
| name | Name of a theme. | yes | theme |

### hassio

10 services

#### `hassio.addon_restart`
**Restart add-on**

Restarts an add-on.

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| addon | The add-on to restart. | yes | addon |

#### `hassio.addon_start`
**Start add-on**

Starts an add-on.

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| addon | The add-on to start. | yes | addon |

#### `hassio.addon_stdin`
**Write data to add-on stdin**

Writes data to the add-on's standard input.

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| addon | The add-on to write to. | yes | addon |

#### `hassio.addon_stop`
**Stop add-on**

Stops an add-on.

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| addon | The add-on to stop. | yes | addon |

#### `hassio.backup_full`
**Create a full backup**

Creates a full backup.

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| compressed | Compresses the backup files. |  | boolean |
| homeassistant_exclude_database | Exclude the Home Assistant database file from the backup. |  | boolean |
| location | Name of a backup network storage to host backups. |  | backup_location |
| name | Optional (default = current date and time). |  | text |
| password | Password to protect the backup with. |  | text |

#### `hassio.backup_partial`
**Create a partial backup**

Creates a partial backup.

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| addons | List of add-ons to include in the backup. Use the name slug… |  | object |
| compressed | Compresses the backup files. |  | boolean |
| folders | List of directories to include in the backup. |  | object |
| homeassistant | Includes Home Assistant settings in the backup. |  | boolean |
| homeassistant_exclude_database | Exclude the Home Assistant database file from the backup. |  | boolean |
| location | Name of a backup network storage to host backups. |  | backup_location |
| name | Optional (default = current date and time). |  | text |
| password | Password to protect the backup with. |  | text |

#### `hassio.host_reboot`
**Reboot the host system**

Reboots the host system.

*No fields*

#### `hassio.host_shutdown`
**Power off the host system**

Powers off the host system.

*No fields*

#### `hassio.restore_full`
**Restore from full backup**

Restores from full backup.

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| password | Optional password. |  | text |
| slug | Slug of backup to restore from. | yes | text |

#### `hassio.restore_partial`
**Restore from partial backup**

Restores from a partial backup.

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| addons | List of add-ons to restore from the backup. Use the name sl… |  | object |
| folders | List of directories to restore from the backup. |  | object |
| homeassistant | Restores Home Assistant. |  | boolean |
| password | Optional password. |  | text |
| slug | Slug of backup to restore from. | yes | text |

### home_connect

2 services

#### `home_connect.change_setting`
**Change setting**

Changes a setting.

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| device_id | ID of the device. | yes | device |
| key | Key of the setting. | yes | text |
| value | Value of the setting. | yes | object |

#### `home_connect.set_program_and_options`
**Set program and options**

Starts or selects a program with options or sets the options for the active or the selected program.

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| affects_to | Selects if the program affected by the action should be the… | yes | select [active_program, selected_program] |
| **cleaning_robot_options** | *cleaning_robot_options* | | *group* |
|  ↳ consumer_products_cleaning_robot_option_cleaning_mode |  |  | select [consumer_products_cleaning_robot_enum_type_cleaning_modes_silent, consumer_products_cleaning_robot_enum_type_cleaning_modes_standard, consumer_products_cleaning_robot_enum_type_cleaning_modes_power] |
|  ↳ consumer_products_cleaning_robot_option_reference_map_id |  |  | select [consumer_products_cleaning_robot_enum_type_available_maps_temp_map, consumer_products_cleaning_robot_enum_type_available_maps_map1, consumer_products_cleaning_robot_enum_type_available_maps_map2, consumer_products_cleaning_robot_enum_type_available_maps_map3] |
| **coffee_maker_options** | *coffee_maker_options* | | *group* |
|  ↳ consumer_products_coffee_maker_option_bean_amount |  |  | select [consumer_products_coffee_maker_enum_type_bean_amount_very_mild, consumer_products_coffee_maker_enum_type_bean_amount_mild, consumer_products_coffee_maker_enum_type_bean_amount_mild_plus, consumer_products_coffee_maker_enum_type_bean_amount_normal, consumer_products_coffee_maker_enum_type_bean_amount_normal_plus, consumer_products_coffee_maker_enum_type_bean_amount_strong (+10)] |
|  ↳ consumer_products_coffee_maker_option_bean_container |  |  | select [consumer_products_coffee_maker_enum_type_bean_container_selection_right, consumer_products_coffee_maker_enum_type_bean_container_selection_left] |
|  ↳ consumer_products_coffee_maker_option_coffee_milk_ratio |  |  | select [consumer_products_coffee_maker_enum_type_coffee_milk_ratio_10_percent, consumer_products_coffee_maker_enum_type_coffee_milk_ratio_20_percent, consumer_products_coffee_maker_enum_type_coffee_milk_ratio_25_percent, consumer_products_coffee_maker_enum_type_coffee_milk_ratio_30_percent, consumer_products_coffee_maker_enum_type_coffee_milk_ratio_40_percent, consumer_products_coffee_maker_enum_type_coffee_milk_ratio_50_percent (+9)] |
|  ↳ consumer_products_coffee_maker_option_coffee_temperature |  |  | select [consumer_products_coffee_maker_enum_type_coffee_temperature_88_c, consumer_products_coffee_maker_enum_type_coffee_temperature_90_c, consumer_products_coffee_maker_enum_type_coffee_temperature_92_c, consumer_products_coffee_maker_enum_type_coffee_temperature_94_c, consumer_products_coffee_maker_enum_type_coffee_temperature_95_c, consumer_products_coffee_maker_enum_type_coffee_temperature_96_c] |
|  ↳ consumer_products_coffee_maker_option_fill_quantity |  |  | number (min=0.0, step=1.0, ml) |
|  ↳ consumer_products_coffee_maker_option_flow_rate |  |  | select [consumer_products_coffee_maker_enum_type_flow_rate_normal, consumer_products_coffee_maker_enum_type_flow_rate_intense, consumer_products_coffee_maker_enum_type_flow_rate_intense_plus] |
|  ↳ consumer_products_coffee_maker_option_hot_water_temperature |  |  | select [consumer_products_coffee_maker_enum_type_hot_water_temperature_white_tea, consumer_products_coffee_maker_enum_type_hot_water_temperature_green_tea, consumer_products_coffee_maker_enum_type_hot_water_temperature_black_tea, consumer_products_coffee_maker_enum_type_hot_water_temperature_50_c, consumer_products_coffee_maker_enum_type_hot_water_temperature_55_c, consumer_products_coffee_maker_enum_type_hot_water_temperature_60_c (+19)] |
|  ↳ consumer_products_coffee_maker_option_multiple_beverages |  |  | boolean |
| device_id | ID of the device. | yes | device |
| **dish_washer_options** | *dish_washer_options* | | *group* |
|  ↳ b_s_h_common_option_start_in_relative |  |  | number (min=0.0, step=1.0, s) |
|  ↳ dishcare_dishwasher_option_brilliance_dry |  |  | boolean |
|  ↳ dishcare_dishwasher_option_eco_dry |  |  | boolean |
|  ↳ dishcare_dishwasher_option_extra_dry |  |  | boolean |
|  ↳ dishcare_dishwasher_option_half_load |  |  | boolean |
|  ↳ dishcare_dishwasher_option_hygiene_plus |  |  | boolean |
|  ↳ dishcare_dishwasher_option_intensiv_zone |  |  | boolean |
|  ↳ dishcare_dishwasher_option_silence_on_demand |  |  | boolean |
|  ↳ dishcare_dishwasher_option_vario_speed_plus |  |  | boolean |
|  ↳ dishcare_dishwasher_option_zeolite_dry |  |  | boolean |
| **dryer_options** | *dryer_options* | | *group* |
|  ↳ laundry_care_dryer_option_drying_target |  |  | select [laundry_care_dryer_enum_type_drying_target_iron_dry, laundry_care_dryer_enum_type_drying_target_gentle_dry, laundry_care_dryer_enum_type_drying_target_cupboard_dry, laundry_care_dryer_enum_type_drying_target_cupboard_dry_plus, laundry_care_dryer_enum_type_drying_target_extra_dry] |
| **hood_options** | *hood_options* | | *group* |
|  ↳ cooking_hood_option_intensive_level |  |  | select [cooking_hood_enum_type_intensive_stage_intensive_stage_off, cooking_hood_enum_type_intensive_stage_intensive_stage1, cooking_hood_enum_type_intensive_stage_intensive_stage2] |
|  ↳ cooking_hood_option_venting_level |  |  | select [cooking_hood_enum_type_stage_fan_off, cooking_hood_enum_type_stage_fan_stage_01, cooking_hood_enum_type_stage_fan_stage_02, cooking_hood_enum_type_stage_fan_stage_03, cooking_hood_enum_type_stage_fan_stage_04, cooking_hood_enum_type_stage_fan_stage_05] |
| **oven_options** | *oven_options* | | *group* |
|  ↳ b_s_h_common_option_duration |  |  | number (min=0.0, step=1.0, s) |
|  ↳ cooking_oven_option_fast_pre_heat |  |  | boolean |
|  ↳ cooking_oven_option_setpoint_temperature |  |  | number (min=0.0, step=1.0, °C/°F) |
| program | Program to select |  | select [consumer_products_cleaning_robot_program_cleaning_clean_all, consumer_products_cleaning_robot_program_cleaning_clean_map, consumer_products_cleaning_robot_program_basic_go_home, consumer_products_coffee_maker_program_beverage_ristretto, consumer_products_coffee_maker_program_beverage_espresso, consumer_products_coffee_maker_program_beverage_espresso_doppio (+148)] |
| **warming_drawer_options** | *warming_drawer_options* | | *group* |
|  ↳ cooking_oven_option_warming_level |  |  | select [cooking_oven_enum_type_warming_level_low, cooking_oven_enum_type_warming_level_medium, cooking_oven_enum_type_warming_level_high] |
| **washer_options** | *washer_options* | | *group* |
|  ↳ b_s_h_common_option_finish_in_relative |  |  | number (min=0.0, step=1.0, s) |
|  ↳ laundry_care_washer_option_i_dos1_active |  |  | boolean |
|  ↳ laundry_care_washer_option_i_dos2_active |  |  | boolean |
|  ↳ laundry_care_washer_option_spin_speed |  |  | select [laundry_care_washer_enum_type_spin_speed_off, laundry_care_washer_enum_type_spin_speed_r_p_m_400, laundry_care_washer_enum_type_spin_speed_r_p_m_600, laundry_care_washer_enum_type_spin_speed_r_p_m_700, laundry_care_washer_enum_type_spin_speed_r_p_m_800, laundry_care_washer_enum_type_spin_speed_r_p_m_900 (+8)] |
|  ↳ laundry_care_washer_option_temperature |  |  | select [laundry_care_washer_enum_type_temperature_cold, laundry_care_washer_enum_type_temperature_g_c_20, laundry_care_washer_enum_type_temperature_g_c_30, laundry_care_washer_enum_type_temperature_g_c_40, laundry_care_washer_enum_type_temperature_g_c_50, laundry_care_washer_enum_type_temperature_g_c_60 (+7)] |
|  ↳ laundry_care_washer_option_vario_perfect |  |  | select [laundry_care_common_enum_type_vario_perfect_off, laundry_care_common_enum_type_vario_perfect_eco_perfect, laundry_care_common_enum_type_vario_perfect_speed_perfect] |

### homeassistant

13 services

#### `homeassistant.check_config`
**Check configuration**

Checks the Home Assistant YAML-configuration files for errors. Errors will be shown in the Home Assistant logs.

*No fields*

#### `homeassistant.reload_all`
**Reload all**

Reloads all YAML configuration that can be reloaded without restarting Home Assistant.

*No fields*

#### `homeassistant.reload_config_entry`
**Reload config entry**

Reloads the specified config entry.

**Target**: entity; device

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| entry_id | The configuration entry ID of the entry to be reloaded. |  | config_entry |

#### `homeassistant.reload_core_config`
**Reload Core configuration**

Reloads the Core configuration from the YAML-configuration.

*No fields*

#### `homeassistant.reload_custom_templates`
**Reload custom Jinja2 templates**

Reloads Jinja2 templates found in the `custom_templates` folder in your config. New values will be applied on the next render of the template.

*No fields*

#### `homeassistant.restart`
**Restart**

Restarts Home Assistant.

*No fields*

#### `homeassistant.save_persistent_states`
**Save persistent states**

Saves the persistent states immediately. Maintains the normal periodic saving interval.

*No fields*

#### `homeassistant.set_location`
**Set location**

Updates the Home Assistant location.

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| elevation | Elevation of your location above sea level. |  | number (step=any) |
| latitude | Latitude of your location. | yes | number (min=-90.0, max=90.0, step=any) |
| longitude | Longitude of your location. | yes | number (min=-180.0, max=180.0, step=any) |

#### `homeassistant.stop`
**Stop**

Stops Home Assistant.

*No fields*

#### `homeassistant.toggle`
**Generic toggle**

Generic action to toggle devices on/off under any domain.

**Target**: entity

*No fields*

#### `homeassistant.turn_off`
**Generic turn off**

Generic action to turn devices off under any domain.

**Target**: entity

*No fields*

#### `homeassistant.turn_on`
**Generic turn on**

Generic action to turn devices on under any domain.

**Target**: entity

*No fields*

#### `homeassistant.update_entity`
**Update entity**

Forces one or more entities to update their data.

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| entity_id | List of entities to force update. | yes | entity |

### homekit

3 services

#### `homekit.reload`
**Reload**

Reloads HomeKit and re-processes the YAML-configuration.

*No fields*

#### `homekit.reset_accessory`
**Reset accessory**

Resets a HomeKit accessory.

**Target**: entity

*No fields*

#### `homekit.unpair`
**Unpair an accessory or bridge**

Forcefully removes all pairings from an accessory to allow re-pairing. Use this action if the accessory is no longer responsive and you want to avoid deleting and re-adding the entry. Room locations and accessory preferences will be lost.

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| device_id | Device to unpair. | yes | device |

### huawei_solar

12 services

#### `huawei_solar.forcible_charge`
**Forcible Charge**

Forcible Charge of the battery for a certain time

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| device_id | Must be a 'Batteries' device | yes | device |
| duration | Duration of the charge | yes | number (min=1.0, max=1440.0, step=1.0, minutes) |
| power | Wattage used for the charge | yes | text |

#### `huawei_solar.forcible_charge_soc`
**Forcible Charge to a SoC level**

Forcible Charge of the battery to a certain State of Charge level

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| device_id | Must be a 'Batteries' device | yes | device |
| power | Wattage used for the charge | yes | text |
| target_soc | State of Charge that must be reached | yes | number (min=12.0, max=100.0, step=1.0, %) |

#### `huawei_solar.forcible_discharge`
**Forcible Discharge**

Forcible Discharge of the battery for a certain time

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| device_id | Must be a 'Batteries' device | yes | device |
| duration | Duration of the discharge | yes | number (min=1.0, max=1440.0, step=1.0, minutes) |
| power | Wattage used for the discharge | yes | text |

#### `huawei_solar.forcible_discharge_soc`
**Forcible Discharge to a SoC level**

Forcible Discharge of the battery to a certain State of Charge level

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| device_id | Must be a 'Batteries' device | yes | device |
| power | Wattage used for the discharge | yes | text |
| target_soc | State of Charge that must be reached | yes | number (min=12.0, max=100.0, step=1.0, %) |

#### `huawei_solar.reset_maximum_feed_grid_power`
**Set Active Power Control to Maximum Feed Grid Power**

Set Active Power Control to the default Unlimited mode

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| device_id | When an EMMA is present, it must be an 'EMMA' device. Other… | yes | device |

#### `huawei_solar.set_capacity_control_periods`
**Set Capacity Control Periods**

Set Capacity Control Periods

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| device_id | Must be a 'Batteries' device | yes | device |
| periods | One period per line. Format: '[start time]-[end time]/[days… | yes | text (multiline) |

#### `huawei_solar.set_di_active_power_scheduling`
**Set Active Power Control to 'DI active scheduling'**

Set Active Power Control to 'DI active scheduling'

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| device_id | Must be a 'Inverter' device | yes | device |

#### `huawei_solar.set_maximum_feed_grid_power`
**Limit the power fed to the grid**

Sets Active Power Control to 'Power-limited grid connection' with the given wattage

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| device_id | When an EMMA is present, it must be an 'EMMA' device. Other… | yes | device |
| power | Maximum Wattage | yes | text |

#### `huawei_solar.set_maximum_feed_grid_power_percent`
**Limit the power fed to the grid to percentage**

Sets Active Power Control to 'Power-limited grid connection (%)' with the given percentage

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| device_id | When an EMMA is present, it must be an 'EMMA' device. Other… | yes | device |
| power_percentage | Maximum Percentage | yes | number (min=0.0, max=100.0, step=1.0, %) |

#### `huawei_solar.set_tou_periods`
**Set TOU Periods**

Sets Time Of Use Periods

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| device_id | When an EMMA is present, it must be an 'EMMA' device. Other… | yes | device |
| periods | One period per line. For Huawei LUNA2000 batteries: '[start… | yes | text (multiline) |

#### `huawei_solar.set_zero_power_grid_connection`
**Set Active Power Control to 'Zero power grid connection'**

Set Active Power Control to 'Zero power grid connection'

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| device_id | When an EMMA is present, it must be an 'EMMA' device. Other… | yes | device |

#### `huawei_solar.stop_forcible_charge`
**Stop the forcible charge or discharge**

Cancel the running forcible charge command

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| device_id | Must be a 'Batteries' device | yes | device |

### input_boolean

4 services

#### `input_boolean.reload`
**Reload**

Reloads helpers from the YAML-configuration.

*No fields*

#### `input_boolean.toggle`
**Toggle**

Toggles the helper on/off.

**Target**: entity: input_boolean

*No fields*

#### `input_boolean.turn_off`
**Turn off**

Turns off the helper.

**Target**: entity: input_boolean

*No fields*

#### `input_boolean.turn_on`
**Turn on**

Turns on the helper.

**Target**: entity: input_boolean

*No fields*

### input_button

2 services

#### `input_button.press`
**Press**

Mimics the physical button press on the device.

**Target**: entity: input_button

*No fields*

#### `input_button.reload`
**Reload**

Reloads helpers from the YAML-configuration.

*No fields*

### input_datetime

2 services

#### `input_datetime.reload`
**Reload**

Reloads helpers from the YAML-configuration.

*No fields*

#### `input_datetime.set_datetime`
**Set**

Sets the date and/or time.

**Target**: entity: input_datetime

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| date | The target date. |  | text |
| datetime | The target date & time. |  | text |
| time | The target time. |  | time |
| timestamp | The target date & time, expressed by a UNIX timestamp. |  | number (min=0.0, max=9.223372036854776e+18, step=1.0) |

### input_number

4 services

#### `input_number.decrement`
**Decrement**

Decrements the current value by 1 step.

**Target**: entity: input_number

*No fields*

#### `input_number.increment`
**Increment**

Increments the current value by 1 step.

**Target**: entity: input_number

*No fields*

#### `input_number.reload`
**Reload**

Reloads helpers from the YAML-configuration.

*No fields*

#### `input_number.set_value`
**Set**

Sets the value.

**Target**: entity: input_number

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| value | The target value. | yes | number (min=0.0, max=9.223372036854776e+18, step=0.001) |

### input_select

7 services

#### `input_select.reload`
**Reload**

Reloads helpers from the YAML-configuration.

*No fields*

#### `input_select.select_first`
**First**

Selects the first option.

**Target**: entity: input_select

*No fields*

#### `input_select.select_last`
**Last**

Selects the last option.

**Target**: entity: input_select

*No fields*

#### `input_select.select_next`
**Next**

Selects the next option.

**Target**: entity: input_select

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| cycle | If the option should cycle from the last to the first optio… |  | boolean |

#### `input_select.select_option`
**Select**

Selects an option.

**Target**: entity: input_select

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| option | Option to be selected. | yes | state |

#### `input_select.select_previous`
**Previous**

Selects the previous option.

**Target**: entity: input_select

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| cycle | If the option should cycle from the first to the last optio… |  | boolean |

#### `input_select.set_options`
**Set options**

Sets the options.

**Target**: entity: input_select

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| options | List of options. | yes | text |

### input_text

2 services

#### `input_text.reload`
**Reload**

Reloads helpers from the YAML-configuration.

*No fields*

#### `input_text.set_value`
**Set**

Sets the value.

**Target**: entity: input_text

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| value | The target value. | yes | text |

### knx

5 services

#### `knx.event_register`
**Register knx_event**

Adds or removes group addresses to knx_event filter for triggering `knx_event`s. Only addresses added with this action can be removed.

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| address | Group address(es) that shall be added or removed. Lists are… | yes | object |
| remove | Whether the group address(es) will be removed. | yes | boolean |
| type | If set, the payload will be decoded as given DPT in the eve… |  | text |

#### `knx.exposure_register`
**Expose to KNX bus**

Adds or removes exposures to KNX bus. Only exposures added with this action can be removed.

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| address | Group address state or attribute updates will be sent to. G… | yes | text |
| attribute | Attribute of the entity that shall be sent to the KNX bus. … |  | text |
| default | Default value to send to the bus if the state or attribute … |  | object |
| entity_id | Entity ID whose state or attribute shall be exposed. | yes | entity |
| remove | Whether the exposure should be removed. Only the 'Address' … | yes | boolean |
| type | Telegrams will be encoded as given DPT. 'binary' and all KN… | yes | text |

#### `knx.read`
**Read from KNX bus**

Sends GroupValueRead requests to the KNX bus. Response can be used from `knx_event` and will be processed in KNX entities.

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| address | Group address(es) to send read request to. Lists will read … | yes | object |

#### `knx.reload`
**Reload**

Reloads the KNX integration.

*No fields*

#### `knx.send`
**Send to KNX bus**

Sends arbitrary data directly to the KNX bus.

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| address | Group address(es) to write to. Lists will send to multiple … | yes | object |
| payload | Payload to send to the bus. Integers are treated as DPT 1/2… | yes | object |
| response | Whether the telegram should be sent as a `GroupValueRespons… | yes | boolean |
| type | If set, the payload will not be sent as raw bytes, but enco… |  | text |

### light

3 services

#### `light.toggle`
**Toggle**

Toggles one or more lights, from on to off, or off to on, based on their current state.

**Target**: entity: light

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| **advanced_fields** | *advanced_fields* | | *group* |
|  ↳ brightness |  |  | number (min=0.0, max=255.0, step=1.0) |
|  ↳ color_name |  |  | select [homeassistant, aliceblue, antiquewhite, aqua, aquamarine, azure (+142)] |
|  ↳ color_temp |  |  | color_temp |
|  ↳ flash |  |  | select [long, short] |
|  ↳ hs_color |  |  | object |
|  ↳ profile |  |  | text |
|  ↳ rgbw_color |  |  | object |
|  ↳ rgbww_color |  |  | object |
|  ↳ white |  |  | constant |
|  ↳ xy_color |  |  | object |
| brightness_pct | Number indicating the percentage of full brightness, where … |  | number (min=0.0, max=100.0, step=1.0, %) |
| color_temp_kelvin | Color temperature in Kelvin. |  | color_temp |
| effect | Light effect. |  | text |
| rgb_color | The color in RGB format. A list of three integers between 0… |  | RGB color |
| transition | Duration it takes to get to next state. |  | number (min=0.0, max=300.0, step=1.0, seconds) |

#### `light.turn_off`
**Turn off**

Turns off one or more lights.

**Target**: entity: light

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| **advanced_fields** | *advanced_fields* | | *group* |
|  ↳ flash |  |  | select [long, short] |
| transition | Duration it takes to get to next state. |  | number (min=0.0, max=300.0, step=1.0, seconds) |

#### `light.turn_on`
**Turn on**

Turns on one or more lights and adjusts their properties, even when they are turned on already.

**Target**: entity: light

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| **advanced_fields** | *advanced_fields* | | *group* |
|  ↳ brightness |  |  | number (min=0.0, max=255.0, step=1.0) |
|  ↳ brightness_step |  |  | number (min=-225.0, max=255.0, step=1.0) |
|  ↳ color_name |  |  | select [homeassistant, aliceblue, antiquewhite, aqua, aquamarine, azure (+142)] |
|  ↳ color_temp |  |  | color_temp |
|  ↳ flash |  |  | select [long, short] |
|  ↳ hs_color |  |  | object |
|  ↳ profile |  |  | text |
|  ↳ rgbw_color |  |  | object |
|  ↳ rgbww_color |  |  | object |
|  ↳ white |  |  | constant |
|  ↳ xy_color |  |  | object |
| brightness_pct | Number indicating the percentage of full brightness, where … |  | number (min=0.0, max=100.0, step=1.0, %) |
| brightness_step_pct | Change brightness by a percentage. |  | number (min=-100.0, max=100.0, step=1.0, %) |
| color_temp_kelvin | Color temperature in Kelvin. |  | color_temp |
| effect | Light effect. |  | text |
| rgb_color | The color in RGB format. A list of three integers between 0… |  | RGB color |
| transition | Duration it takes to get to next state. |  | number (min=0.0, max=300.0, step=1.0, seconds) |

### lock

3 services

#### `lock.lock`
**Lock**

Locks a lock.

**Target**: entity: lock

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| code | Code used to lock the lock. |  | text |

#### `lock.open`
**Open**

Opens a lock.

**Target**: entity: lock

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| code | Code used to open the lock. |  | text |

#### `lock.unlock`
**Unlock**

Unlocks a lock.

**Target**: entity: lock

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| code | Code used to unlock the lock. |  | text |

### logbook

1 services

#### `logbook.log`
**Log**

Tracks a custom activity.

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| domain | Determines which icon is used in the activity. The icon ill… |  | text |
| entity_id | Entity to reference in the activity. |  | entity |
| message | Message of the activity. | yes | text |
| name | Custom name for an entity, can be referenced using the 'Ent… | yes | text |

### logger

2 services

#### `logger.set_default_level`
**Set default level**

Sets the default log level for integrations.

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| level | Default severity level for all integrations. |  | select [debug, info, warning, error, fatal, critical] |

#### `logger.set_level`
**Set level**

Sets the log level for one or more integrations.

*No fields*

### media_player

24 services

#### `media_player.browse_media`
**Browse media**

Browses the available media.

**Target**: entity: media_player

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| media_content_id | The ID of the content to browse. Integration dependent. |  | text |
| media_content_type | The type of the content to browse, such as image, music, TV… |  | text |

#### `media_player.clear_playlist`
**Clear playlist**

Removes all items from the playlist.

**Target**: entity: media_player

*No fields*

#### `media_player.join`
**Join**

Groups media players together for synchronous playback. Only works on supported multiroom audio systems.

**Target**: entity: media_player

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| group_members | The players which will be synced with the playback specifie… | yes | entity (media_player) |

#### `media_player.media_next_track`
**Next**

Selects the next track.

**Target**: entity: media_player

*No fields*

#### `media_player.media_pause`
**Pause**

Pauses.

**Target**: entity: media_player

*No fields*

#### `media_player.media_play`
**Play**

Starts playing.

**Target**: entity: media_player

*No fields*

#### `media_player.media_play_pause`
**Play/Pause**

Toggles play/pause.

**Target**: entity: media_player

*No fields*

#### `media_player.media_previous_track`
**Previous**

Selects the previous track.

**Target**: entity: media_player

*No fields*

#### `media_player.media_seek`
**Seek**

Allows you to go to a different part of the media that is currently playing.

**Target**: entity: media_player

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| seek_position | Target position in the currently playing media. The format … | yes | number (min=0.0, max=9.223372036854776e+18, step=0.01) |

#### `media_player.media_stop`
**Stop**

Stops playing.

**Target**: entity: media_player

*No fields*

#### `media_player.play_media`
**Play media**

Starts playing specified media.

**Target**: entity: media_player

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| announce | If the media should be played as an announcement. |  | boolean |
| enqueue | If the content should be played now or be added to the queu… |  | select [play, next, add, replace] |
| media | The media selected to play. | yes | media |

#### `media_player.repeat_set`
**Set repeat**

Sets the repeat mode.

**Target**: entity: media_player

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| repeat | Whether the media (one or all) should be played in a loop o… | yes | select [off, all, one] |

#### `media_player.search_media`
**Search media**

Searches the available media.

**Target**: entity: media_player

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| media_content_id | The ID of the content to browse. Integration dependent. |  | text |
| media_content_type | The type of the content to browse, such as image, music, TV… |  | text |
| media_filter_classes | List of media classes to filter the search results by. |  | text |
| search_query | The term to search for. | yes | text |

#### `media_player.select_sound_mode`
**Select sound mode**

Selects a specific sound mode.

**Target**: entity: media_player

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| sound_mode | Name of the sound mode to switch to. |  | text |

#### `media_player.select_source`
**Select source**

Sends the media player the command to change input source.

**Target**: entity: media_player

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| source | Name of the source to switch to. Platform dependent. | yes | text |

#### `media_player.shuffle_set`
**Set shuffle**

Enables or disables the shuffle mode.

**Target**: entity: media_player

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| shuffle | Whether the media should be played in randomized order or n… | yes | boolean |

#### `media_player.toggle`
**Toggle**

Toggles a media player on/off.

**Target**: entity: media_player

*No fields*

#### `media_player.turn_off`
**Turn off**

Turns off the power of the media player.

**Target**: entity: media_player

*No fields*

#### `media_player.turn_on`
**Turn on**

Turns on the power of the media player.

**Target**: entity: media_player

*No fields*

#### `media_player.unjoin`
**Unjoin**

Removes the player from a group. Only works on platforms which support player groups.

**Target**: entity: media_player

*No fields*

#### `media_player.volume_down`
**Turn down volume**

Turns down the volume.

**Target**: entity: media_player

*No fields*

#### `media_player.volume_mute`
**Mute/unmute volume**

Mutes or unmutes the media player.

**Target**: entity: media_player

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| is_volume_muted | Defines whether or not it is muted. | yes | boolean |

#### `media_player.volume_set`
**Set volume**

Sets the volume level.

**Target**: entity: media_player

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| volume_level | The volume. 0 is inaudible, 1 is the maximum volume. | yes | number (min=0.0, max=1.0, step=0.01) |

#### `media_player.volume_up`
**Turn up volume**

Turns up the volume.

**Target**: entity: media_player

*No fields*

### modbus

4 services

#### `modbus.reload`
**Reload**

Reloads all Modbus entities.

*No fields*

#### `modbus.stop`
**Stop**

Stops a Modbus hub.

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| hub | Modbus hub name. |  | text |

#### `modbus.write_coil`
**Write coil**

Writes to a Modbus coil.

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| address | Address of the register to write to. | yes | number (min=0.0, max=65535.0, step=1.0) |
| hub | Modbus hub name. |  | text |
| slave | Address of the Modbus unit/server. |  | number (min=1.0, max=255.0, step=1.0) |
| state | State to write. | yes | object |

#### `modbus.write_register`
**Write register**

Writes to a Modbus holding register.

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| address | Address of the holding register to write to. | yes | number (min=0.0, max=65535.0, step=1.0) |
| hub | Modbus hub name. |  | text |
| slave | Address of the Modbus unit/server. |  | number (min=1.0, max=255.0, step=1.0) |
| value | Value (single value or array) to write. | yes | object |

### mqtt

3 services

#### `mqtt.dump`
**Export**

Writes all messages on a specific topic into the `mqtt_dump.txt` file in your configuration folder.

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| duration | How long we should listen for messages in seconds. |  | number (min=1.0, max=300.0, step=1.0, seconds) |
| topic | Topic to listen to. |  | text |

#### `mqtt.publish`
**Publish**

Publishes a message to an MQTT topic.

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| evaluate_payload | If 'Payload' is a Python bytes literal, evaluate the bytes … |  | boolean |
| payload | The payload to publish. Publishes an empty message if not p… |  | template |
| qos | Quality of Service to use. 0: At most once. 1: At least onc… |  | select [0, 1, 2] |
| retain | If the message should have the retain flag set. If set, the… |  | boolean |
| topic | Topic to publish to. | yes | text |

#### `mqtt.reload`
**Reload**

Reloads MQTT entities from the YAML-configuration.

*No fields*

### notify

11 services

#### `notify.lg_tv`
**Send a notification with lg_tv**

Sends a notification message using the lg_tv service.

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| data |  |  | object |
| message |  | yes | text |
| target |  |  | object |
| title |  |  | text |

#### `notify.mobile_app_hennings_cg_iphone`
**Send a notification via mobile_app_hennings_cg_iphone**

Sends a notification message using the mobile_app_hennings_cg_iphone integration.

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| data |  |  | object |
| message |  | yes | text |
| target |  |  | object |
| title |  |  | text |

#### `notify.mobile_app_hennings_iphone`
**Send a notification via mobile_app_hennings_iphone**

Sends a notification message using the mobile_app_hennings_iphone integration.

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| data |  |  | object |
| message |  | yes | text |
| target |  |  | object |
| title |  |  | text |

#### `notify.mobile_app_iphone16_hp_hs`
**Send a notification via mobile_app_iphone16_hp_hs**

Sends a notification message using the mobile_app_iphone16_hp_hs integration.

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| data |  |  | object |
| message |  | yes | text |
| target |  |  | object |
| title |  |  | text |

#### `notify.mobile_app_iphone8`
**Send a notification via mobile_app_iphone8**

Sends a notification message using the mobile_app_iphone8 integration.

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| data |  |  | object |
| message |  | yes | text |
| target |  |  | object |
| title |  |  | text |

#### `notify.mobile_app_iphone_13_cgp`
**Send a notification via mobile_app_iphone_13_cgp**

Sends a notification message using the mobile_app_iphone_13_cgp integration.

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| data |  |  | object |
| message |  | yes | text |
| target |  |  | object |
| title |  |  | text |

#### `notify.mobile_app_redminote13`
**Send a notification via mobile_app_redminote13**

Sends a notification message using the mobile_app_redminote13 integration.

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| data |  |  | object |
| message |  | yes | text |
| target |  |  | object |
| title |  |  | text |

#### `notify.mobile_app_schmohlchens_iphone`
**Send a notification via mobile_app_schmohlchens_iphone**

Sends a notification message using the mobile_app_schmohlchens_iphone integration.

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| data |  |  | object |
| message |  | yes | text |
| target |  |  | object |
| title |  |  | text |

#### `notify.notify`
**Send a notification with notify**

Sends a notification message using the notify service.

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| data |  |  | object |
| message |  | yes | text |
| target |  |  | object |
| title |  |  | text |

#### `notify.persistent_notification`
**Send a persistent notification**

Sends a notification that is visible in the notifications panel.

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| data | Some integrations provide extended functionality via this f… |  | object |
| message | Message body of the notification. | yes | text |
| title | Title of the notification. |  | text |

#### `notify.send_message`
**Send a notification message**

Sends a notification message.

**Target**: entity: notify

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| message | Your notification message. | yes | text |
| title | Title for your notification message. |  | text |

### number

1 services

#### `number.set_value`
**Set**

Sets the value of a number.

**Target**: entity: number

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| value | The target value to set. | yes | text |

### openweathermap

1 services

#### `openweathermap.get_minute_forecast`
**Get minute forecast**

Retrieves a minute-by-minute weather forecast for one hour.

**Target**: entity: weather

*No fields*

### persistent_notification

3 services

#### `persistent_notification.create`
**Create**

Shows a notification on the notifications panel.

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| message | Message body of the notification. | yes | text |
| notification_id | ID of the notification. This new notification will overwrit… |  | text |
| title | Optional title of the notification. |  | text |

#### `persistent_notification.dismiss`
**Dismiss**

Deletes a notification from the notifications panel.

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| notification_id | ID of the notification to be deleted. | yes | text |

#### `persistent_notification.dismiss_all`
**Dismiss all**

Deletes all notifications from the notifications panel.

*No fields*

### person

1 services

#### `person.reload`
**Reload**

Reloads persons from the YAML-configuration.

*No fields*

### pyscript

2 services

#### `pyscript.jupyter_kernel_start`
**Start Jupyter kernel**

Starts a jupyter kernel for interactive use; Called by Jupyter front end and should generally not be used by users

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| control_port | Control port number |  | number (min=10240.0, max=65535.0, step=1.0) |
| hb_port | Heartbeat port number |  | number (min=10240.0, max=65535.0, step=1.0) |
| iopub_port | IOPub port number |  | number (min=10240.0, max=65535.0, step=1.0) |
| ip | IP address to connect to Jupyter front end |  | text |
| kernel_name | Kernel name | yes | text |
| key | Used for signing | yes | text |
| shell_port | Shell port number |  | number (min=10240.0, max=65535.0, step=1.0) |
| signature_scheme | Signing algorithm |  | select [hmac-sha256] |
| stdin_port | Stdin port number |  | number (min=10240.0, max=65535.0, step=1.0) |
| transport | Transport type |  | select [tcp, udp] |

#### `pyscript.reload`
**Reload pyscript**

Reloads all available pyscripts and restart triggers

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| global_ctx | Only reload this specific global context (file or app) |  | text |

### recorder

5 services

#### `recorder.disable`
**Disable**

Stops the recording of events and state changes.

*No fields*

#### `recorder.enable`
**Enable**

Starts the recording of events and state changes.

*No fields*

#### `recorder.get_statistics`
**Get statistics**

Retrieves statistics data for entities within a specific time period.

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| end_time | The end time for the statistics query. If omitted, returns … |  | datetime |
| period | The time period to group statistics by. | yes | select [5minute, hour, day, week, month] |
| start_time | The start time for the statistics query. | yes | datetime |
| statistic_ids | The entity IDs or statistic IDs to return statistics for. | yes | statistic |
| types | The types of statistics values to return. | yes | select [change, last_reset, max, mean, min, state (+1)] |
| units | Optional unit conversion mapping. |  | object |

#### `recorder.purge`
**Purge**

Starts purge task - to clean up old data from your database.

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| apply_filter | Apply `entity_id` and `event_type` filters in addition to t… |  | boolean |
| keep_days | Number of days to keep the data in the database. Starting t… |  | number (min=0.0, max=365.0, step=1.0, days) |
| repack | Attempt to save disk space by rewriting the entire database… |  | boolean |

#### `recorder.purge_entities`
**Purge entities**

Starts a purge task to remove the data related to specific entities from your database.

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| domains | List of domains for which the data needs to be removed from… |  | object |
| entity_globs | List of glob patterns used to select the entities for which… |  | object |
| entity_id | List of entities for which the data is to be removed from t… |  | entity |
| keep_days | Number of days to keep the data for rows matching the filte… |  | number (min=0.0, max=365.0, step=1.0, days) |

### remote

6 services

#### `remote.delete_command`
**Delete command**

Deletes a command or a list of commands from the database.

**Target**: entity: remote

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| command | The single command or the list of commands to be deleted. | yes | object |
| device | Device from which commands will be deleted. |  | text |

#### `remote.learn_command`
**Learn command**

Learns a command or a list of commands from a device.

**Target**: entity: remote

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| alternative | If code must be stored as an alternative. This is useful fo… |  | boolean |
| command | A single command or a list of commands to learn. |  | object |
| command_type | The type of command to be learned. |  | select [ir, rf] |
| device | Device ID to learn command from. |  | text |
| timeout | Timeout for the command to be learned. |  | number (min=0.0, max=60.0, step=5.0, seconds) |

#### `remote.send_command`
**Send command**

Sends a command or a list of commands to a device.

**Target**: entity: remote

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| command | A single command or a list of commands to send. | yes | object |
| delay_secs | The time you want to wait in between repeated commands. |  | number (min=0.0, max=60.0, step=0.1, seconds) |
| device | Device ID to send command to. |  | text |
| hold_secs | The time you want to have it held before the release is sen… |  | number (min=0.0, max=60.0, step=0.1, seconds) |
| num_repeats | The number of times you want to repeat the commands. |  | number (min=0.0, max=255.0, step=1.0) |

#### `remote.toggle`
**Toggle**

Sends the toggle command.

**Target**: entity: remote

*No fields*

#### `remote.turn_off`
**Turn off**

Sends the turn off command.

**Target**: entity: remote

*No fields*

#### `remote.turn_on`
**Turn on**

Sends the turn on command.

**Target**: entity: remote

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| activity | Activity ID or activity name to be started. |  | text |

### reolink

2 services

#### `reolink.play_chime`
**Play chime**

Plays a ringtone on a Reolink Chime.

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| device_id | The Reolink Chime to play the ringtone on. | yes | device |
| ringtone | Ringtone to play. | yes | select [citybird, originaltune, pianokey, loop, attraction, hophop (+4)] |

#### `reolink.ptz_move`
**PTZ move**

Moves the camera with a specific speed.

**Target**: entity: button

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| speed | PTZ move speed. | yes | number (min=1.0, max=64.0, step=1.0) |

### scene

5 services

#### `scene.apply`
**Apply**

Activates a scene with configuration.

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| entities | List of entities and their target state. | yes | object |
| transition | Time it takes the devices to transition into the states def… |  | number (min=0.0, max=300.0, step=1.0, seconds) |

#### `scene.create`
**Create**

Creates a new scene.

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| entities | List of entities and their target state. If your entities a… |  | object |
| scene_id | The entity ID of the new scene. | yes | text |
| snapshot_entities | List of entities to be included in the snapshot. By taking … |  | entity |

#### `scene.delete`
**Delete**

Deletes a dynamically created scene.

**Target**: entity: scene

*No fields*

#### `scene.reload`
**Reload**

Reloads the scenes from the YAML-configuration.

*No fields*

#### `scene.turn_on`
**Activate**

Activates a scene.

**Target**: entity: scene

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| transition | Time it takes the devices to transition into the states def… |  | number (min=0.0, max=300.0, step=1.0, seconds) |

### schedule

2 services

#### `schedule.get_schedule`
**Get schedule**

Retrieves the configured time ranges of one or multiple schedules.

**Target**: entity: schedule

*No fields*

#### `schedule.reload`
**Reload**

Reloads schedules from the YAML-configuration.

*No fields*

### script

8 services

#### `script.bad_og_handle_vent`
**Bad_OG_Handle_Vent**

*No fields*

#### `script.bad_og_light_handle`
**Bad_OG_Light_Handle**

*No fields*

#### `script.reload`
**Reload**

Reloads all the available scripts.

*No fields*

#### `script.temperatures`
**Temperatures**

*No fields*

#### `script.toggle`
**Toggle**

Starts a script if it isn't running, stops it otherwise.

**Target**: entity: script

*No fields*

#### `script.turn_off`
**Turn off**

Stops a running script.

**Target**: entity: script

*No fields*

#### `script.turn_on`
**Turn on**

Runs the sequence of actions defined in a script.

**Target**: entity: script

*No fields*

#### `script.zirkulationspumpe_handle`
**Zirkulationspumpe_handle**

*No fields*

### select

5 services

#### `select.select_first`
**First**

Selects the first option.

**Target**: entity: select

*No fields*

#### `select.select_last`
**Last**

Selects the last option.

**Target**: entity: select

*No fields*

#### `select.select_next`
**Next**

Selects the next option.

**Target**: entity: select

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| cycle | If the option should cycle from the last to the first. |  | boolean |

#### `select.select_option`
**Select**

Selects an option.

**Target**: entity: select

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| option | Option to be selected. | yes | state |

#### `select.select_previous`
**Previous**

Selects the previous option.

**Target**: entity: select

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| cycle | If the option should cycle from the first to the last. |  | boolean |

### siren

3 services

#### `siren.toggle`
**Toggle**

Toggles the siren on/off.

**Target**: entity: siren

*No fields*

#### `siren.turn_off`
**Turn off**

Turns the siren off.

**Target**: entity: siren

*No fields*

#### `siren.turn_on`
**Turn on**

Turns the siren on.

**Target**: entity: siren

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| duration | Number of seconds the sound is played. Must be supported by… |  | text |
| tone | The tone to emit. When `available_tones` property is a map,… |  | text |
| volume_level | The volume. 0 is inaudible, 1 is the maximum volume. Must b… |  | number (min=0.0, max=1.0, step=0.05) |

### switch

3 services

#### `switch.toggle`
**Toggle**

Toggles a switch on/off.

**Target**: entity: switch

*No fields*

#### `switch.turn_off`
**Turn off**

Turns a switch off.

**Target**: entity: switch

*No fields*

#### `switch.turn_on`
**Turn on**

Turns a switch on.

**Target**: entity: switch

*No fields*

### synology_dsm

2 services

#### `synology_dsm.reboot`
**Reboot**

Reboots the NAS. This action is deprecated and will be removed in future release. Please use the corresponding button entity.

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| serial | Serial of the NAS to reboot; required when multiple NAS are… |  | text |

#### `synology_dsm.shutdown`
**Shutdown**

Shutdowns the NAS. This action is deprecated and will be removed in future release. Please use the corresponding button entity.

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| serial | Serial of the NAS to shutdown; required when multiple NAS a… |  | text |

### system_log

2 services

#### `system_log.clear`
**Clear**

Deletes all log entries.

*No fields*

#### `system_log.write`
**Write**

Write log entry.

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| level | Log level. |  | select [debug, info, warning, error, critical] |
| logger | Logger name under which to log the message. Defaults to `sy… |  | text |
| message | Message to log. | yes | text |

### template

1 services

#### `template.reload`
**Reload**

Reloads template entities from the YAML-configuration.

*No fields*

### text

1 services

#### `text.set_value`
**Set value**

Sets the value.

**Target**: entity: text

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| value | Enter your text. | yes | text |

### thermal_comfort

1 services

#### `thermal_comfort.reload`
**Reload**

Reload all Thermal Comfort entities.

*No fields*

### timer

6 services

#### `timer.cancel`
**Cancel**

Resets a timer's duration to the last known initial value without firing the timer finished event.

**Target**: entity: timer

*No fields*

#### `timer.change`
**Change**

Changes a timer by adding or subtracting a given duration.

**Target**: entity: timer

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| duration | Duration to add to or subtract from the running timer. | yes | text |

#### `timer.finish`
**Finish**

Finishes a running timer earlier than scheduled.

**Target**: entity: timer

*No fields*

#### `timer.pause`
**Pause**

Pauses a running timer, retaining the remaining duration for later continuation.

**Target**: entity: timer

*No fields*

#### `timer.reload`
**Reload**

Reloads timers from the YAML-configuration.

*No fields*

#### `timer.start`
**Start**

Starts a timer or restarts it with a provided duration.

**Target**: entity: timer

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| duration | Custom duration to restart the timer with. |  | text |

### tts

4 services

#### `tts.clear_cache`
**Clear TTS cache**

Removes all cached text-to-speech files and purges the memory.

*No fields*

#### `tts.cloud_say`
**Say a TTS message with cloud**

Say something using text-to-speech on a media player with cloud.

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| cache |  |  | boolean |
| entity_id |  | yes | entity (media_player) |
| language |  |  | text |
| message |  | yes | text |
| options |  |  | object |

#### `tts.google_translate_say`
**Say a TTS message with google_translate**

Say something using text-to-speech on a media player with google_translate.

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| cache |  |  | boolean |
| entity_id |  | yes | entity (media_player) |
| language |  |  | text |
| message |  | yes | text |
| options |  |  | object |

#### `tts.speak`
**Speak**

Speaks something using text-to-speech on a media player.

**Target**: entity: tts

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| cache | Stores this message locally so that when the text is reques… |  | boolean |
| language | Language to use for speech generation. |  | text |
| media_player_entity_id | Media players to play the message. | yes | entity (media_player) |
| message | The text you want to convert into speech so that you can li… | yes | text |
| options | A dictionary containing integration-specific options. |  | object |

### update

3 services

#### `update.clear_skipped`
**Clear skipped update**

Removes the skipped version marker from an update.

**Target**: entity: update

*No fields*

#### `update.install`
**Install update**

Installs an update for a device or service.

**Target**: entity: update

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| backup | If supported by the integration, this creates a backup befo… |  | boolean |
| version | The version to install. If omitted, the latest version will… |  | text |

#### `update.skip`
**Skip update**

Marks currently available update as skipped.

**Target**: entity: update

*No fields*

### utility_meter

2 services

#### `utility_meter.calibrate`
**Calibrate**

Calibrates a utility meter sensor.

**Target**: entity: sensor

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| value | Value to which set the meter. | yes | text |

#### `utility_meter.reset`
**Reset**

Resets all counters of a utility meter.

**Target**: entity: select

*No fields*

### vacuum

8 services

#### `vacuum.clean_spot`
**Clean spot**

Tells the vacuum cleaner to do a spot clean-up.

**Target**: entity: vacuum

*No fields*

#### `vacuum.locate`
**Locate**

Locates the vacuum cleaner robot.

**Target**: entity: vacuum

*No fields*

#### `vacuum.pause`
**Pause**

Pauses the cleaning task.

**Target**: entity: vacuum

*No fields*

#### `vacuum.return_to_base`
**Return to dock**

Tells the vacuum cleaner to return to its dock.

**Target**: entity: vacuum

*No fields*

#### `vacuum.send_command`
**Send command**

Sends a command to the vacuum cleaner.

**Target**: entity: vacuum

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| command | Command to execute. The commands are integration-specific. | yes | text |
| params | Parameters for the command. The parameters are integration-… |  | object |

#### `vacuum.set_fan_speed`
**Set fan speed**

Sets the fan speed of the vacuum cleaner.

**Target**: entity: vacuum

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| fan_speed | Fan speed. The value depends on the integration. Some integ… | yes | text |

#### `vacuum.start`
**Start**

Starts or resumes the cleaning task.

**Target**: entity: vacuum

*No fields*

#### `vacuum.stop`
**Stop**

Stops the current cleaning task.

**Target**: entity: vacuum

*No fields*

### valve

5 services

#### `valve.close_valve`
**Close**

Closes a valve.

**Target**: entity: valve

*No fields*

#### `valve.open_valve`
**Open**

Opens a valve.

**Target**: entity: valve

*No fields*

#### `valve.set_valve_position`
**Set position**

Moves a valve to a specific position.

**Target**: entity: valve

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| position | Target position. | yes | number (min=0.0, max=100.0, step=1.0, %) |

#### `valve.stop_valve`
**Stop**

Stops the valve movement.

**Target**: entity: valve

*No fields*

#### `valve.toggle`
**Toggle**

Toggles a valve open/closed.

**Target**: entity: valve

*No fields*

### watchman

1 services

#### `watchman.report`
**Report**

Run the Watchman report

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| **advanced_options** | *advanced_options* | | *group* |
|  ↳ action |  |  | text |
|  ↳ chunk_size |  |  | number (min=0.0, max=100000.0, step=1.0) |
|  ↳ create_file |  |  | boolean |
|  ↳ data |  |  |  |
| parse_config | Parse configuration files before generating the report. Usu… |  | boolean |

### water_heater

5 services

#### `water_heater.set_away_mode`
**Set away mode**

Turns away mode on/off.

**Target**: entity: water_heater

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| away_mode | New value of away mode. | yes | boolean |

#### `water_heater.set_operation_mode`
**Set operation mode**

Sets the operation mode.

**Target**: entity: water_heater

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| operation_mode | New value of the operation mode. For a list of possible mod… | yes | text |

#### `water_heater.set_temperature`
**Set temperature**

Sets the target temperature.

**Target**: entity: water_heater

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| operation_mode | New value of the operation mode. For a list of possible mod… |  | text |
| temperature | New target temperature for the water heater. | yes | number (min=0.0, max=100.0, step=0.5, °) |

#### `water_heater.turn_off`
**Turn off**

Turns water heater off.

**Target**: entity: water_heater

*No fields*

#### `water_heater.turn_on`
**Turn on**

Turns water heater on.

**Target**: entity: water_heater

*No fields*

### weather

1 services

#### `weather.get_forecasts`
**Get forecasts**

Retrieves the forecast from selected weather services.

**Target**: entity: weather

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| type | The scope of the weather forecast. | yes | select [daily, hourly, twice_daily] |

### webostv

3 services

#### `webostv.button`
**Button**

Sends a button press command.

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| button | Name of the button to press.  Known possible values are LEF… | yes | text |
| entity_id | Name(s) of the webOS TV entities where to run the API metho… | yes | entity (media_player) |

#### `webostv.command`
**Command**

Sends a command.

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| command | Endpoint of the command. | yes | text |
| entity_id | Name(s) of the webOS TV entities where to run the API metho… | yes | entity (media_player) |
| payload | An optional payload to provide to the endpoint in the forma… |  | object |

#### `webostv.select_sound_output`
**Select sound output**

Sends the TV the command to change sound output.

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| entity_id | Name(s) of the webOS TV entities to change sound output on. | yes | entity (media_player) |
| sound_output | Name of the sound output to switch to. | yes | text |

### workday

1 services

#### `workday.check_date`
**Check date**

Checks if a given date is a workday.

**Target**: entity

| Field | Description | Required | Type |
|-------|-------------|----------|------|
| check_date | Date to check if workday. |  | date |

### zone

1 services

#### `zone.reload`
**Reload**

Reloads zones from the YAML-configuration.

*No fields*

## Devices

| Device | Manufacturer | Model | Area |
|--------|--------------|-------|------|
| Küche | Apple | HomePod Mini | Küche |
| LG TV | LG | OLED77C19LA | Living Room |
| HP OfficeJet 8010 series | HP | HP OfficeJet 8010 series | Office |
| gaesteWC-esp32 | Espressif | esp32dev | guest_WC |
| Batteries | Huawei |  | mechanical |
| Battery_1 | Huawei | LUNA 2000 | mechanical |
| heatdistreg-esp32 | Espressif | esp32dev | mechanical |
| Inverter | Huawei | SUN2000-20K-MB0 01076373-006 | mechanical |
| KNX Interface |  | SCN-IP100.03 IP Router mit Sec | mechanical |
| Power meter |  |  | mechanical |
| shelly3em_main | Shelly | Shelly 3EM | mechanical |
| shelly3em_main Phase A | Shelly | Shelly 3EM | mechanical |
| shelly3em_main Phase B | Shelly | Shelly 3EM | mechanical |
| shelly3em_main Phase C | Shelly | Shelly 3EM | mechanical |
| Audi A6 Avant e-tron | Audi | Audi A6 Avant e-tron e-tron |  |
| Audi connect | audiconnect | integration |  |
| Backup | Home Assistant | Home Assistant Backup |  |
| balkon_east | Forecast.Solar | personal |  |
| balkon_west | Forecast.Solar | personal |  |
| Battery Simulator | hif2k1 | integration |  |
| battery_sim: balkon_battery_5k |  |  |  |
| c386d1df8bbc | HA Dev | Script Container |  |
| CAM_Engel | Reolink | Reolink Elite XPro PoE |  |
| CAM_Terrasse | Reolink | Reolink Elite XPro PoE |  |
| Cooktop | Siemens | EX877NX68E |  |
| devbox-192-168-0-51 | HA Dev | Script Container |  |
| Dishwasher | Neff | S155HB800E |  |
| ds214 | Synology | DS214 |  |
| ds214 (Drive 1) | Seagate | ST10000NM0046 |  |
| ds214 (Drive 2) | Unknown | HUH721010ALE601 |  |
| ds214 (Volume 1) | Synology | DS214 |  |
| ds214 (Volume 2) | Synology | DS214 |  |
| Electricity Maps | Electricity Maps |  |  |
| EPEX Spot | mampfes | integration |  |
| EPEX Spot Data | SMARD.de | DE-LU |  |
| EPEX Spot Data | Awattar API V1 | de |  |
| ESPHome Device Builder | ESPHome | Home Assistant Add-on |  |
| Forecast | Met.no | Forecast |  |
| Get HACS | HACS Add-ons Repository | Home Assistant Add-on |  |
| HACS | hacs.xyz |  |  |
| HASS Bridge:21064 | Home Assistant | HomeBridge |  |
| Henning’s CG iphone | Apple | iPhone14,5 |  |
| Henning’s iPhone | Apple | iPhone14,7 |  |
| Home | Open-Meteo |  |  |
| Home Assistant Core | Home Assistant | Home Assistant Core |  |
| Home Assistant Host | Home Assistant | Home Assistant Host |  |
| Home Assistant Operating System | Home Assistant | Home Assistant Operating System |  |
| Home Assistant Supervisor | Home Assistant | Home Assistant Supervisor |  |
| Huawei Solar | wlcrs | integration |  |
| iPhone | Apple, Inc | iPhone14,5 |  |
| iPhone | Apple, Inc | iPhone14,5 |  |
| iPhone 13 CGp | Apple | iPhone14,5 |  |
| iPhone16 HP HS | Apple | iPhone17,3 |  |
| iPhone8 | Apple | iPhone10,1 |  |
| keller_flur_treppe_v3 | Espressif | esp32dev |  |
| Node-RED | Home Assistant Community Add-ons | Home Assistant Add-on |  |
| Node-RED Companion | zachowj | integration |  |
| OpenWeatherMap | OpenWeather |  |  |
| Outside v2 | Thermal Comfort | Virtual Device |  |
| PV AI Forecast | Homelab | pv-forecast |  |
| pyscript | craigbarratt | integration |  |
| redminote13 | Xiaomi | 23090RA98G |  |
| RX-V473 92D3E3 | YAMAHA CORPORATION | RX-V473 |  |
| Rüdiger | Roborock | roborock.vacuum.s5e |  |
| Schmöhlchens iPhone | Apple | iPhone14,2 |  |
| Shelly_Keller_Flur | Shelly | Shelly Plus 1PM |  |
| Smart EV Charging | Homelab | smart-ev-charging |  |
| SmartThinQ LGE Sensors | ollo69 | integration |  |
| SpeedTest |  |  |  |
| Spotify Hen Sch | Spotify AB | Spotify premium |  |
| Studio Code Server | Home Assistant Community Add-ons | Home Assistant Add-on |  |
| Sun |  |  |  |
| System Monitor | System Monitor |  |  |
| Terminal & SSH | Official add-ons | Home Assistant Add-on |  |
| Thermal Comfort | dolezsa | integration |  |
| Variable | snarky-snark | integration |  |
| Washer | LGE | F_R7_Y___W.A__QEUK (DEVICE_WASHER) |  |
| Watchman | dummylabs | Watchman |  |
| Watchman | dummylabs | integration |  |
| Workday Sensor | python-holidays | 0.82 |  |

---

*Regenerate this file with `python scripts/ha-export.py`*
