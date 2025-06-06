# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import json
import os
import pytest
import unittest

from azure.cli.testsdk.scenario_tests import AllowLargeResponse, live_only
from azure.cli.testsdk import ScenarioTest
from azure.cli.core.azclierror import InvalidArgumentValueError, RequiredArgumentMissingError, AzureInternalError

from .utils import get_test_subscription_id, get_test_resource_group, get_test_workspace, get_test_workspace_location, get_test_workspace_location_for_dft, issue_cmd_with_param_missing, get_test_workspace_storage, get_test_workspace_random_name, get_test_capabilities
from ..._client_factory import _get_data_credentials
from ...commands import transform_output
from ...operations.workspace import WorkspaceInfo, DEPLOYMENT_NAME_PREFIX
from ...operations.target import TargetInfo
from ...operations.job import (
    _parse_blob_url,
    _validate_max_poll_wait_secs,
    _convert_numeric_params,
    _construct_filter_query,
    _construct_orderby_expression,
    ERROR_MSG_INVALID_ORDER_ARGUMENT,
    ERROR_MSG_MISSING_ORDERBY_ARGUMENT)

TEST_DIR = os.path.abspath(os.path.join(os.path.abspath(__file__), '..'))


class QuantumJobsScenarioTest(ScenarioTest):

    @live_only()
    def test_jobs(self):
        # set current workspace:
        self.cmd(f'az quantum workspace set -g {get_test_resource_group()} -w {get_test_workspace()} -l {get_test_workspace_location()}')

        # list
        targets = self.cmd('az quantum target list -o json').get_output_in_json()
        assert len(targets) > 0

    # @pytest.fixture(autouse=True)
    # def _pass_fixtures(self, capsys):
    #     self.capsys = capsys
    # # See "TODO" in issue_cmd_with_param_missing un utils.py

    def test_job_errors(self):
        issue_cmd_with_param_missing(self, "az quantum job cancel", "az quantum job cancel -g MyResourceGroup -w MyWorkspace -l MyLocation -j yyyyyyyy-yyyy-yyyy-yyyy-yyyyyyyyyyyy\nCancel an Azure Quantum job by id.")
        issue_cmd_with_param_missing(self, "az quantum job output", "az quantum job output -g MyResourceGroup -w MyWorkspace -l MyLocation -j yyyyyyyy-yyyy-yyyy-yyyy-yyyyyyyyyyyy -o table\nPrint the results of a successful Azure Quantum job.")
        issue_cmd_with_param_missing(self, "az quantum job show", "az quantum job show -g MyResourceGroup -w MyWorkspace -l MyLocation -j yyyyyyyy-yyyy-yyyy-yyyy-yyyyyyyyyyyy --query status\nGet the status of an Azure Quantum job.")
        issue_cmd_with_param_missing(self, "az quantum job wait", "az quantum job wait -g MyResourceGroup -w MyWorkspace -l MyLocation -j yyyyyyyy-yyyy-yyyy-yyyy-yyyyyyyyyyyy --max-poll-wait-secs 60 -o table\nWait for completion of a job, check at 60 second intervals.")

    def test_parse_blob_url(self):
        sas = "sv=2018-03-28&sr=c&sig=some-sig&sp=racwl"
        url = f"https://accountname.blob.core.windows.net/containername/rawOutputData?{sas}"
        args = _parse_blob_url(url)

        self.assertEqual(args['account_name'], "accountname")
        self.assertEqual(args['container'], "containername")
        self.assertEqual(args['blob'], "rawOutputData")
        self.assertEqual(args['sas_token'], sas)

    def test_transform_output(self):
        # Call with a good histogram
        test_job_results = '{"Histogram":["[0,0,0]",0.125,"[1,0,0]",0.125,"[0,1,0]",0.125,"[1,1,0]",0.125]}'
        table = transform_output(json.loads(test_job_results))
        table_row = table[0]
        hist_row = table_row['']
        second_char = hist_row[1]
        self.assertEqual(second_char, "\u2588")    # Expecting a "Full Block" character here

        # Give it a malformed histogram
        test_job_results = '{"Histogram":["[0,0,0]",0.125,"[1,0,0]",0.125,"[0,1,0]",0.125,"[1,1,0]"]}'
        table = transform_output(json.loads(test_job_results))
        self.assertEqual(table, json.loads(test_job_results))    # No transform should be done if input param is bad

        # Call with output from a failed job
        test_job_results = \
            '{\
                "beginExecutionTime": "2022-02-25T18:57:26.093000+00:00",\
                "cancellationTime": null,\
                "containerUri": "https://foo...",\
                "costEstimate": null,\
                "creationTime": "2022-02-25T18:56:53.275035+00:00",\
                "endExecutionTime": "2022-02-25T18:57:26.093000+00:00",\
                "errorData": {\
                    "code": "InsufficientResources",\
                    "message": "Too many qubits requested"\
                },\
                "id": "11111111-2222-3333-4444-555555555555",\
                "inputDataFormat": "microsoft.ionq-ir.v2",\
                "inputDataUri": "https://bar...",\
                "inputParams": {\
                    "shots": "500"\
                },\
                "isCancelling": false,\
                "metadata": {\
                    "entryPointInput": {\"Qubits\":null},\
                    "outputMappingBlobUri": "https://baz..."\
                },\
                "name": "",\
                "outputDataFormat": "microsoft.quantum-results.v1",\
                "outputDataUri": "https://quux...",\
                "providerId": "ionq",\
                "status": "Failed",\
                "tags": [],\
                "target": "ionq.simulator"\
            }'

        table = transform_output(json.loads(test_job_results))
        self.assertEqual(table['Status'], "Failed")
        self.assertEqual(table['Error Code'], "InsufficientResources")
        self.assertEqual(table['Error Message'], "Too many qubits requested")
        self.assertEqual(table['Target'], "ionq.simulator")
        self.assertEqual(table['Job ID'], "11111111-2222-3333-4444-555555555555")
        self.assertEqual(table['Submission Time'], "2022-02-25T18:56:53.275035+00:00")

        # Call with missing "status", "code", "message", "target", "id", and "creationTime"
        test_job_results = \
            '{\
                "beginExecutionTime": "2022-02-25T18:57:26.093000+00:00",\
                "cancellationTime": null,\
                "containerUri": "https://foo...",\
                "costEstimate": null,\
                "endExecutionTime": "2022-02-25T18:57:26.093000+00:00",\
                "errorData": {\
                },\
                "inputDataFormat": "microsoft.ionq-ir.v2",\
                "inputDataUri": "https://bar...",\
                "inputParams": {\
                    "shots": "500"\
                },\
                "isCancelling": false,\
                "metadata": {\
                    "entryPointInput": {\"Qubits\":null},\
                    "outputMappingBlobUri": "https://baz..."\
                },\
                "name": "",\
                "outputDataFormat": "microsoft.quantum-results.v1",\
                "outputDataUri": "https://quux...",\
                "providerId": "ionq",\
                "tags": []\
            }'

        table = transform_output(json.loads(test_job_results))
        notFound = "Not found"
        self.assertEqual(table['Status'], notFound)
        self.assertEqual(table['Error Code'], notFound)
        self.assertEqual(table['Error Message'], notFound)
        self.assertEqual(table['Target'], notFound)
        self.assertEqual(table['Job ID'], notFound)
        self.assertEqual(table['Submission Time'], notFound)

    def test_validate_max_poll_wait_secs(self):
        wait_secs = _validate_max_poll_wait_secs(1)
        self.assertEqual(type(wait_secs), float)
        self.assertEqual(wait_secs, 1.0)

        wait_secs = _validate_max_poll_wait_secs("60")
        self.assertEqual(type(wait_secs), float)
        self.assertEqual(wait_secs, 60.0)

        # Invalid values should raise errors
        try:
            wait_secs = _validate_max_poll_wait_secs(0.999999999)
            assert False
        except InvalidArgumentValueError as e:
            assert str(e) == "--max-poll-wait-secs parameter is not valid: 0.999999999"

        try:
            wait_secs = _validate_max_poll_wait_secs(-1.0)
            assert False
        except InvalidArgumentValueError as e:
            assert str(e) == "--max-poll-wait-secs parameter is not valid: -1.0"

        try:
            wait_secs = _validate_max_poll_wait_secs("foobar")
            assert False
        except InvalidArgumentValueError as e:
            assert str(e) == "--max-poll-wait-secs parameter is not valid: foobar"

    def test_convert_numeric_params(self):
        # Show that it converts numeric strings, but doesn't modify params that are already numeric
        test_job_params = {"integer1": "1", "float1.5": "1.5", "integer2": 2, "float2.5": 2.5, "integer3": "3", "float3.5": "3.5"}
        _convert_numeric_params(test_job_params)
        assert test_job_params == {"integer1": 1, "float1.5": 1.5, "integer2": 2, "float2.5": 2.5, "integer3": 3, "float3.5": 3.5}

        # Make sure it doesn't modify non-numeric strings
        test_job_params = {"string1": "string_value1", "string2": "string_value2", "string3": "string_value3"}
        _convert_numeric_params(test_job_params)
        assert test_job_params == {"string1": "string_value1", "string2": "string_value2", "string3": "string_value3"}

        # Make sure it doesn't modify the "tags" list
        test_job_params = {"string1": "string_value1", "tags": ["tag1", "tag2", "3", "4"], "integer1": "1"}
        _convert_numeric_params(test_job_params)
        assert test_job_params == {"string1": "string_value1", "tags": ["tag1", "tag2", "3", "4"], "integer1": 1}

        # Make sure it doesn't modify nested dict like metadata uses
        test_job_params = {"string1": "string_value1", "metadata": {"meta1": "meta_value1", "meta2": "2"}, "integer1": "1"}
        _convert_numeric_params(test_job_params)
        assert test_job_params == {"string1": "string_value1", "metadata": {"meta1": "meta_value1", "meta2": "2"}, "integer1": 1}

    @live_only()
    def test_submit(self):
        test_location = get_test_workspace_location()
        test_resource_group = get_test_resource_group()
        test_workspace_temp = get_test_workspace_random_name()
        test_provider_sku_list = "rigetti/azure-quantum-credits,ionq/aq-internal-testing"
        test_storage = get_test_workspace_storage()

        self.cmd(f"az quantum workspace create -g {test_resource_group} -w {test_workspace_temp} -l {test_location} -a {test_storage} -r {test_provider_sku_list} --skip-autoadd")
        self.cmd(f"az quantum workspace set -g {test_resource_group} -w {test_workspace_temp} -l {test_location}")

        # Submit a job to Rigetti and look for SAS tokens in URIs in the output
        results = self.cmd("az quantum job submit -t rigetti.sim.qvm --job-input-format rigetti.quil.v1 -t rigetti.sim.qvm --job-input-file src/quantum/azext_quantum/tests/latest/input_data/bell-state.quil --job-output-format rigetti.quil-results.v1 -o json").get_output_in_json()
        self.assertIn("?sv=", results["containerUri"])
        self.assertIn("&st=", results["containerUri"])
        self.assertIn("&se=", results["containerUri"])
        self.assertIn("&sp=", results["containerUri"])
        self.assertIn("&sig=", results["containerUri"])

        self.assertIn("?sv=", results["inputDataUri"])
        self.assertIn("&st=", results["inputDataUri"])
        self.assertIn("&se=", results["inputDataUri"])
        self.assertIn("&sp=", results["inputDataUri"])
        self.assertIn("&sig=", results["inputDataUri"])

        self.assertIn("?sv=", results["outputDataUri"])
        self.assertIn("&st=", results["outputDataUri"])
        self.assertIn("&se=", results["outputDataUri"])
        self.assertIn("&sp=", results["outputDataUri"])
        self.assertIn("&sig=", results["outputDataUri"])

        # Run a Quil pass-through job on Rigetti
        results = self.cmd("az quantum run -t rigetti.sim.qvm --job-input-format rigetti.quil.v1 -t rigetti.sim.qvm --job-input-file src/quantum/azext_quantum/tests/latest/input_data/bell-state.quil --job-output-format rigetti.quil-results.v1 -o json").get_output_in_json()
        self.assertIn("ro", results)

        # Run a Qiskit pass-through job on IonQ
        results = self.cmd("az quantum run -t ionq.simulator --shots 100 --job-input-format ionq.circuit.v1 --job-input-file src/quantum/azext_quantum/tests/latest/input_data/Qiskit-3-qubit-GHZ-circuit.json --job-output-format ionq.quantum-results.v1 --job-params count=100 content-type=application/json -o json").get_output_in_json()
        self.assertIn("histogram", results)

        # Test "az quantum job list" output, for filter-params, --skip, --top, and --orderby
        results = self.cmd("az quantum job list --provider-id rigetti -o json").get_output_in_json()
        self.assertIn("rigetti", str(results))

        results = self.cmd("az quantum job list --target-id ionq.simulator -o json").get_output_in_json()
        self.assertIn("ionq.simulator", str(results))

        results = str(self.cmd("az quantum job list --top 1 -o json").get_output_in_json())
        self.assertIn("rigetti", results)
        self.assertTrue("ionq" not in results)

        results = str(self.cmd("az quantum job list --skip 1 -o json").get_output_in_json())
        self.assertIn("ionq", results)

        results = str(self.cmd("az quantum job list --orderby Target --skip 1 -o json").get_output_in_json())
        self.assertIn("rigetti", results)
        self.assertTrue("ionq" not in results)

        self.cmd(f'az quantum workspace delete -g {test_resource_group} -w {test_workspace_temp}')

    @live_only()
    def test_submit_dft(self):
        elements_provider_name = "microsoft-elements"
        elements_capability_name = f"submit.{elements_provider_name}"

        test_capabilities = get_test_capabilities()

        if elements_capability_name not in test_capabilities.split(";"):
            self.skipTest(f"Skipping test_submit_dft: \"{elements_capability_name}\" capability was not found in \"AZURE_QUANTUM_CAPABILITIES\" env variable.")

        test_location = get_test_workspace_location_for_dft()
        test_resource_group = get_test_resource_group()
        test_workspace_temp = get_test_workspace_random_name()
        test_provider_sku_list = f"{elements_provider_name}/elements-internal-testing"
        test_storage = get_test_workspace_storage()

        self.cmd(f"az quantum workspace create -g {test_resource_group} -w {test_workspace_temp} -l {test_location} -a {test_storage} -r \"{test_provider_sku_list}\" --skip-autoadd")
        self.cmd(f"az quantum workspace set -g {test_resource_group} -w {test_workspace_temp} -l {test_location}")

        # Run a "microsoft.dft" job to test that successful job returns proper output
        results = self.cmd("az quantum run -t microsoft.dft --job-input-format microsoft.qc-schema.v1 --job-output-format microsoft.dft-results.v1 --job-input-file src/quantum/azext_quantum/tests/latest/input_data/dft_molecule_success.json -o json").get_output_in_json()
        self.assertIsNotNone(results["results"])
        self.assertTrue(len(results["results"]) == 1)
        self.assertTrue(results["results"][0]["success"])

        # Run a "microsoft.dft" job to test that failed run returns "Job"-object if job didn't produce any output
        # In the test case below the run doesn't produce any output since the job fails on input parameter validation (i.e. taskType: "invalidTask")
        results = self.cmd("az quantum run -t microsoft.dft --job-input-format microsoft.qc-schema.v1 --job-output-format microsoft.dft-results.v1 --job-input-file src/quantum/azext_quantum/tests/latest/input_data/dft_molecule_failure_bad_params.json  -o json").get_output_in_json()
        self.assertIsNotNone(results["results"])
        self.assertTrue(len(results["results"]) == 1)
        self.assertFalse(results["results"][0]["success"])
        self.assertTrue(results["results"][0]["error"]["error_type"] == "input_error")

        # Run a "microsoft.dft" job to test that failed run returns output if it was produced by the job
        # In the test case below the job fails to converge in "maxSteps", but it still produces the output with a detailed message
        results = self.cmd("az quantum run -t microsoft.dft --job-input-format microsoft.qc-schema.v1 --job-output-format microsoft.dft-results.v1 --job-input-file src/quantum/azext_quantum/tests/latest/input_data/dft_molecule_failure_no_convergence.json  -o json").get_output_in_json()
        self.assertIsNotNone(results["results"])
        self.assertTrue(len(results["results"]) == 1)
        self.assertFalse(results["results"][0]["success"])
        self.assertTrue(results["results"][0]["error"]["error_type"] == "convergence_error")

        self.cmd(f'az quantum workspace delete -g {test_resource_group} -w {test_workspace_temp}')

    def test_job_list_param_formating(self):
        # Validate filter query formatting for each param
        #
        # Should return None if params are set to None
        job_type = None
        item_type = None
        provider_id = None
        target_id = None
        job_status = None
        created_after = None
        created_before = None
        job_name = None
        query = _construct_filter_query(job_type, item_type, provider_id, target_id, job_status, created_after, created_before, job_name)
        assert query is None

        job_type = "QuantumComputing"
        query = _construct_filter_query(job_type, item_type, provider_id, target_id, job_status, created_after, created_before, job_name)
        assert query == "JobType eq 'QuantumComputing'"
        job_type = None

        item_type = "job"
        query = _construct_filter_query(job_type, item_type, provider_id, target_id, job_status, created_after, created_before, job_name)
        assert query == "ItemType eq 'job'"
        item_type = None

        provider_id = "Microsoft"
        query = _construct_filter_query(job_type, item_type, provider_id, target_id, job_status, created_after, created_before, job_name)
        assert query == "ProviderId eq 'Microsoft'"
        provider_id = None

        target_id = "Awesome.Quantum.SuperComputer"
        query = _construct_filter_query(job_type, item_type, provider_id, target_id, job_status, created_after, created_before, job_name)
        assert query == "Target eq 'Awesome.Quantum.SuperComputer'"
        target_id = None

        job_status = "Succeeded"        
        query = _construct_filter_query(job_type, item_type, provider_id, target_id, job_status, created_after, created_before, job_name)
        assert query == "State eq 'Succeeded'"
        job_status = None        

        created_after = "2025-01-27"
        query = _construct_filter_query(job_type, item_type, provider_id, target_id, job_status, created_after, created_before, job_name)
        assert query == "CreationTime ge 2025-01-27"
        created_after = None

        created_before = "2025-01-27"
        query = _construct_filter_query(job_type, item_type, provider_id, target_id, job_status, created_after, created_before, job_name)
        assert query == "CreationTime le 2025-01-27"
        created_before = None

        job_name = "TestJob"
        query = _construct_filter_query(job_type, item_type, provider_id, target_id, job_status, created_after, created_before, job_name)
        assert query == "startswith(Name, 'TestJob')"
        job_name = None


        # Validate orderby expression formatting
        # Should return None if params are set to None
        orderby = None
        order = None
        orderby_expression = _construct_orderby_expression(orderby, order)
        assert orderby_expression is None

        # Test valid params
        orderby = "Target"
        orderby_expression = _construct_orderby_expression(orderby, order)
        assert orderby_expression == "Target"

        order = "asc"
        orderby_expression = _construct_orderby_expression(orderby, order)
        assert orderby_expression == "Target asc"

        order = "desc"
        orderby_expression = _construct_orderby_expression(orderby, order)
        assert orderby_expression == "Target desc"

        # Test orderby/order errors
        orderby = "Target"
        order = "foo"
        try:
            orderby_expression = _construct_orderby_expression(orderby, order)
            assert False
        except InvalidArgumentValueError as e:
            assert str(e) == ERROR_MSG_INVALID_ORDER_ARGUMENT

        orderby = ""
        order = "desc"
        try:
            orderby_expression = _construct_orderby_expression(orderby, order)
            assert False
        except RequiredArgumentMissingError as e:
            assert str(e) == ERROR_MSG_MISSING_ORDERBY_ARGUMENT
