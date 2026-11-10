# Copyright (C) 2026 David L F Gaden
"""Operation selection guidance for declared ngspice linear circuits."""
import json
from importlib.resources import files


def catalogue():
    return {'application': {'label': 'ngspice',
                'purpose': 'Analyse ideal linear resistor, capacitor and AC inductor circuits with independently verified DC voltage sweeps, frequency/electrical responses and first-order RC charging curves.',
                'keywords': ['SPICE', 'analogue circuits', 'linear circuit simulation', 'RLC']},
        'searchCases': json.loads(files(__package__).joinpath('search-cases.json').read_text()),
        'requirements':[
        'Use SI ohms, farads, henries, volts, hertz and seconds. Node 0 is ground; other node/component names are bounded lowercase identifiers.',
        'One grounded ideal voltage source, resistors, capacitors and AC-only uncoupled inductors; every node needs a resistor/inductor reference path.',
        'Use shared document source/property editing; this is not a node-graph or imported-netlist authoring interface.',
        'Keep circuit.cir and circuit-summary.json with results.csv to preserve topology and assumptions.',
        'Optional named requirements gate success on checked sampled signed voltage or AC magnitude/gain; inspect worst conditions and signed margins. Finite samples and explicit component variants do not prove a continuous or all-tolerance envelope.'],
        'references':['docs/ngspice.md','src/schemaxis/adaptors/ngspice/readiness.json'],
        'operations':{
            'dcSweep':{'purpose':'Sweep one ideal source through linearly spaced DC voltages and solve an ideal resistor network.',
                       'keywords': ['voltage sweep', 'bias sweep', 'steady state', 'DC analysis', 'resistive divider'],
                       'semantics':['start and stop are source volts; stop must exceed start; points includes both endpoints.',
                                    'Capacitors are open circuits at steady DC; all node voltages are independently checked by nodal equations.'],
                       'examples':[{'reference':'examples/schemaxis/ngspice-minimal.json','purpose':'Verify a resistive divider across six source voltages.'}]},
            'acSweep':{'purpose':'Compute linear RLC network phasor responses, RL filters and damped resonance across linear, decade or octave frequencies with optional source-current/KCL, impedance and passive branch power characterisation.',
                       'keywords': ['frequency response', 'small signal', 'Bode', 'RLC', 'low pass', 'band pass', 'AC analysis', 'input impedance', 'reactive power', 'branch current', 'resistor heating', 'logarithmic frequency', 'samples per octave', 'phase requirement', 'gain dB', 'RMS'],
                       'semantics':['start/stop are positive Hz; spacing selects linear total points or logarithmic decade/octave density; amplitudeConvention explicitly selects peak or rms source volts; output includes real, imaginary, magnitude and phase degrees.',
                                    'Phasors use exp(+j*omega*t); inductor admittance is 1/(j*omega*L). Inductors use henries and are supported only in acSweep.',
                                    'branchProbes derive passive a-to-b currents and powers from checked voltages; portMetrics additionally verifies native -i(vdrive) and derives input impedance/power; phase requirements use principal relative transfer phase and refuse zero magnitude.',
                                    'Reject ideal-inductor loops, inductive shorts across the source and singular/ill-conditioned systems at any requested sample. No mutual coupling or nonlinear models.'],
                       'examples':[{'reference':'examples/schemaxis/ngspice-rc-frequency.json','purpose':'Verify the analytic RC cutoff and phase lag.'},
                                   {'reference':'examples/schemaxis/ngspice-rl-frequency.json','purpose':'Verify an RL low-pass at and above cutoff.'},
                                   {'reference':'examples/schemaxis/ngspice-rlc-resonance.json','purpose':'Verify capacitor voltage in a damped series RLC circuit at and above resonance.'},
                                   {'reference':'examples/schemaxis/ngspice-rlc-parallel.json','purpose':'Verify a resistor-fed parallel LC band-pass across resonance.'}]},
            'rcStep':{'purpose':'Compute a first-order initially uncharged RC capacitor response to a constant source switched on at t=0.',
                      'keywords': ['capacitor charging', 'settling time', 'turn on response', 'transient RC', 'step response'],
                      'semantics':['Exactly one series resistor and grounded capacitor; stop is seconds and must be 0.01–20 RC time constants.',
                                   'Native transient values are resampled uniformly and checked against V*(1-exp(-t/RC)); general transient networks are unsupported.'],
                      'examples':[{'reference':'examples/schemaxis/ngspice-rc-step.json','purpose':'Verify a 5 V RC charging curve across five time constants.'}]}}}
