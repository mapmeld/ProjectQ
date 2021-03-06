#   Copyright 2017 ProjectQ-Framework (www.projectq.ch)
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.

""" Back-end to run quantum program on Rigetti's Forest API."""

import random
import json

from projectq.cengines import BasicEngine
from projectq.meta import get_control_count, LogicalQubitIDTag
from projectq.ops import (NOT,
                          Y,
                          X,
                          Z,
                          T,
                          Tdag,
                          S,
                          Sdag,
                          H,
                          Ph,
                          Rx,
                          Ry,
                          Rz,
                          Measure,
                          Allocate,
                          Deallocate,
                          Barrier,
                          FlushGate)

from ._rigetti_http_client import send, retrieve

RIGETTI_DEVICES = ["8Q-Agave", "19Q-Acorn"]

class RigettiBackend(BasicEngine):
    """
    The Rigetti Backend class, which stores the circuit, transforms it to JSON
    Quil, and sends the circuit through the Rigetti Forest API.
    """
    def __init__(self, use_hardware=False, num_runs=1024, verbose=False,
                 user_id=None, api_key=None, device=RIGETTI_DEVICES[0],
                 retrieve_execution=None):
        """
        Initialize the Backend object.

        Args:
            use_hardware (bool): If True, the code is run on the Rigetti quantum
                chip (instead of using the virtual machine)
            num_runs (int): Number of runs to collect statistics.
                (default is 1024)
            verbose (bool): If True, statistics are printed, in addition to
                the measurement result being registered (at the end of the
                circuit).
            user_id (string): Rigetti API user id
            api_key (string): Rigetti API's API key
            device (string): Device to use ('8Q-Agave', or '19Q-Acorn')
                if use_hardware is set to True. Default is 8Q-Agave.
            retrieve_execution (int): Job ID to retrieve instead of re-
                running the circuit (e.g., if previous run timed out).
        """
        BasicEngine.__init__(self)
        self._reset()
        if use_hardware:
            self.device = device
        else:
            self.device = 'QVM'
        self._num_runs = num_runs
        self._verbose = verbose
        self._user_id = user_id
        self._api_key = api_key
        self._probabilities = dict()
        self.quil = ""
        self._measured_ids = []
        self._allocated_qubits = set()
        self._retrieve_execution = retrieve_execution

    def is_available(self, cmd):
        """
        Return true if the command can be executed.

        Rigetti's quantum chips can do X, Y, Z, T, Tdag, S, Sdag,
        rotation gates, barriers, and CX / CNOT.

        Args:
            cmd (Command): Command for which to check availability
        """
        g = cmd.gate
        if g == Barrier:
            return False
        if g == NOT and get_control_count(cmd) <= 2:
            return True
        if g in (T, Tdag, S, Sdag, H, X, Y, Z):
            return True
        if isinstance(g, (Rx, Ry, Rz, Ph)):
            return True
        if g in (Measure, Allocate, Deallocate):
            return True
        return False

    def _reset(self):
        """ Reset all temporary variables (after flush gate). """
        self._clear = True
        self._measured_ids = []

    def _store(self, cmd):
        """
        Temporarily store the command cmd.

        Translates the command and stores it in a local variable (self._cmds).

        Args:
            cmd: Command to store
        """
        if self._clear:
            self._probabilities = dict()
            self._clear = False
            self.quil = ""
            self._allocated_qubits = set()

        gate = cmd.gate

        if gate == Allocate:
            self._allocated_qubits.add(cmd.qubits[0][0].id)
            return

        if gate == Deallocate:
            return

        if gate == Measure:
            assert len(cmd.qubits) == 1 and len(cmd.qubits[0]) == 1
            qb_id = cmd.qubits[0][0].id
            logical_id = None
            for t in cmd.tags:
                if isinstance(t, LogicalQubitIDTag):
                    logical_id = t.logical_qubit_id
                    break
            assert logical_id is not None
            self._measured_ids += [logical_id]
        elif gate == NOT and get_control_count(cmd) == 1:
            ctrl_pos = cmd.control_qubits[0].id
            qb_pos = cmd.qubits[0][0].id
            self.quil += "\nCNOT {} {}".format(ctrl_pos, qb_pos)
        elif gate == NOT and get_control_count(cmd) == 2:
            ctrl_pos = cmd.control_qubits[0].id
            ctrl2_pos = cmd.control_qubits[1].id
            qb_pos = cmd.qubits[0][0].id
            self.quil += "\nCCNOT {} {} {}".format(ctrl_pos, ctrl2_pos, qb_pos)
        elif isinstance(gate, (Rx, Ry, Rz, Ph)):
            assert get_control_count(cmd) < 2
            qb_pos = cmd.qubits[0][0].id

            gate_str = str(gate).upper().replace('PH(', 'PHASE(')

            if (get_control_count(cmd) == 1):
                ctrl_pos = cmd.control_qubits[0].id
                self.quil += "\nCONTROLLED {} {} {}".format(gate_str, ctrl_pos, qb_pos)
            else:
                self.quil += "\n{} {}".format(gate_str, qb_pos)
        else:
            assert get_control_count(cmd) < 2
            if str(gate) in self._gate_names:
                gate_str = self._gate_names[str(gate)]
            else:
                gate_str = str(gate).upper()

            qb_pos = cmd.qubits[0][0].id

            if (get_control_count(cmd) == 1):
                ctrl_pos = cmd.control_qubits[0].id
                self.quil += "\nCONTROLLED {} {} {}".format(gate_str, ctrl_pos, qb_pos)
            else:
                self.quil += "\n{} {}".format(gate_str, qb_pos)

    def _logical_to_physical(self, qb_id):
        """
        Return the physical location of the qubit with the given logical id.

        Args:
            qb_id (int): ID of the logical qubit whose position should be
                returned.
        """
        assert self.main_engine.mapper is not None
        mapping = self.main_engine.mapper.current_mapping
        if qb_id not in mapping:
            raise RuntimeError("Unknown qubit id {}. Please make sure "
                               "eng.flush() was called and that the qubit "
                               "was eliminated during optimization."
                               .format(qb_id))
        return mapping[qb_id]

    def get_probabilities(self, qureg):
        """
        Return the list of basis states with corresponding probabilities.

        The measured bits are ordered according to the supplied quantum
        register, i.e., the left-most bit in the state-string corresponds to
        the first qubit in the supplied quantum register.

        Warning:
            Only call this function after the circuit has been executed!

        Args:
            qureg (list<Qubit>): Quantum register determining the order of the
                qubits.

        Returns:
            probability_dict (dict): Dictionary mapping n-bit strings to
            probabilities.

        Raises:
            RuntimeError: If no data is available (i.e., if the circuit has
                not been executed). Or if a qubit was supplied which was not
                present in the circuit (might have gotten optimized away).
        """
        if len(self._probabilities) == 0:
            raise RuntimeError("Please, run the circuit first!")

        probability_dict = dict()

        for state in self._probabilities:
            mapped_state = ['0'] * len(qureg)
            for i in range(len(qureg)):
                mapped_state[i] = state[self._logical_to_physical(qureg[i].id)]
            probability = self._probabilities[state]
            probability_dict["".join(mapped_state)] = probability

        return probability_dict

    def _run(self):
        """
        Run the circuit.

        Send the circuit via the Rigetti Forest API (JSON Quil) using the provided user
        data / ask for user id & api key.
        """
        if self.quil == "":
            return
        # finally: add measurements (no intermediate measurements are allowed)
        for measured_id in self._measured_ids:
            qb_loc = self.main_engine.mapper.current_mapping[measured_id]
            self.quil += "\nMEASURE {} [{}]".format(qb_loc, qb_loc)

        max_qubit_id = max(self._allocated_qubits)
        # todo: establish max qubits
        quil = self.quil
        info = {}
        info['quils'] = [{'quil': quil.strip()}]
        info['shots'] = self._num_runs
        info['maxCredits'] = 5
        info['backend'] = {'name': self.device}

        try:
            if self._retrieve_execution is None:
                res = send(info, device=self.device,
                           user_id=self._user_id, api_key=self._api_key,
                           shots=self._num_runs, verbose=self._verbose)
            else:
                res = retrieve(device=self.device, user_id=self._user_id,
                               api_key=self._api_key,
                               jobid=self._retrieve_execution)

            counts = {}
            for result in res:
                combined = ''
                for val in result:
                    combined += str(val)
                if combined not in counts:
                    counts[combined] = 1
                else:
                    counts[combined] += 1

            # Determine random outcome
            P = random.random()
            p_sum = 0.
            measured = ""
            for state in counts:
                probability = counts[state] * 1. / self._num_runs
                state = list(reversed(state))
                state = "".join(state)
                p_sum += probability
                star = ""
                if p_sum >= P and measured == "":
                    measured = state
                    star = "*"
                self._probabilities[state] = probability
                if self._verbose and probability > 0:
                    print(str(state) + " with p = " + str(probability) +
                          star)

            class QB():
                def __init__(self, ID):
                    self.id = ID

            # register measurement result
            for ID in self._measured_ids:
                location = self._logical_to_physical(ID)
                result = int(measured[location])
                self.main_engine.set_measurement_result(QB(ID), result)
            self._reset()
        except TypeError:
            raise Exception("Failed to run the circuit. Aborting.")

    def receive(self, command_list):
        """
        Receives a command list and, for each command, stores it until
        completion.

        Args:
            command_list: List of commands to execute
        """
        for cmd in command_list:
            if not cmd.gate == FlushGate():
                self._store(cmd)
            else:
                self._run()
                self._reset()

    """
    Mapping of gate names from our gate objects to the Rigetti Quil representation.
    """
    _gate_names = {str(Tdag): "DAGGER T",
                   str(Sdag): "DAGGER S",
                   str(Ph): "PHASE"}
