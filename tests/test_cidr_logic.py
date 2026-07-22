"""The pure CIDR logic, ported case for case from FindNextCIDRRange's test suite so the two
projects answer identically."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from lib.cidr import analyze_cidr, first_free_subnet


class TestAnalyzeCidr:
    def test_the_smallest_azure_subnet_answers_the_full_arithmetic(self):
        result = analyze_cidr("10.0.0.0/29")

        assert result["validAzureSubnet"] is True
        assert result["totalAddresses"] == 8
        assert result["azureReservedAddresses"] == 5
        assert result["usableAddresses"] == 3
        assert result["reserved"]["networkAddress"] == "10.0.0.0"
        assert result["reserved"]["defaultGateway"] == "10.0.0.1"
        assert result["reserved"]["azureDns"] == ["10.0.0.2", "10.0.0.3"]
        assert result["reserved"]["broadcast"] == "10.0.0.7"
        assert result["firstUsable"] == "10.0.0.4"
        assert result["lastUsable"] == "10.0.0.6"
        assert result["reason"] is None

    def test_a_slash_30_is_answered_not_errored_with_the_reason_why(self):
        result = analyze_cidr("10.0.0.0/30")

        assert result["validAzureSubnet"] is False
        assert result["totalAddresses"] == 4
        assert result["usableAddresses"] == 0
        assert result["reserved"] is None
        assert "reserves 5 addresses" in result["reason"]

    def test_a_slash_24_loses_exactly_five_addresses_to_azure(self):
        result = analyze_cidr("192.168.1.0/24")

        assert result["totalAddresses"] == 256
        assert result["usableAddresses"] == 251
        assert result["reserved"]["defaultGateway"] == "192.168.1.1"
        assert result["reserved"]["broadcast"] == "192.168.1.255"
        assert result["firstUsable"] == "192.168.1.4"
        assert result["lastUsable"] == "192.168.1.254"

    @pytest.mark.parametrize(
        ("cidr", "expected"),
        [
            ("10.0.0.0/2", True),
            ("10.0.0.0/29", True),
            ("10.0.0.0/1", False),
            ("0.0.0.0/0", False),
            ("10.0.0.0/30", False),
            ("10.0.0.0/31", False),
            ("10.0.0.0/32", False),
        ],
    )
    def test_azure_allows_subnets_from_slash_2_through_slash_29(self, cidr, expected):
        assert analyze_cidr(cidr)["validAzureSubnet"] is expected

    def test_host_bits_are_dropped_and_reported_via_the_normalized_form(self):
        result = analyze_cidr("10.0.0.5/24")

        assert result["cidr"] == "10.0.0.5/24"
        assert result["normalized"] == "10.0.0.0/24"
        assert result["validAzureSubnet"] is True

    @pytest.mark.parametrize(
        ("value", "message"),
        [
            (None, "cidr is null"),
            ("", "cidr is null"),
            ("   ", "cidr is null"),
            ("banana", "cidr must include a prefix length, for example 10.0.0.0/24"),
            ("10.0.0.0", "cidr must include a prefix length, for example 10.0.0.0/24"),
            ("banana/24", "not a valid CIDR: banana/24"),
            ("10.0.0.999/24", "not a valid CIDR: 10.0.0.999/24"),
            ("10.0.0.0/33", "not a valid CIDR: 10.0.0.0/33"),
            ("2001:db8::/64", "only IPv4 CIDRs are supported; Azure IPv6 subnets are always /64"),
        ],
    )
    def test_unparseable_input_raises_with_the_reason(self, value, message):
        with pytest.raises(ValueError, match="^" + __import__("re").escape(message) + "$"):
            analyze_cidr(value)


class TestFirstFreeSubnet:
    def test_an_empty_vnet_yields_the_first_block(self):
        assert first_free_subnet(["10.30.0.0/24"], [], 26) == ("10.30.0.0/26", "10.30.0.0/24")

    def test_the_next_free_block_after_existing_subnets_is_proposed(self):
        # The standalone example stack: a /24 with two /26 subnets already carved.
        proposed, space = first_free_subnet(
            ["10.30.0.0/24"], ["10.30.0.0/26", "10.30.0.64/26"], 26
        )
        assert (proposed, space) == ("10.30.0.128/26", "10.30.0.0/24")

    def test_a_gap_between_subnets_is_filled_first(self):
        proposed, _ = first_free_subnet(["10.30.0.0/24"], ["10.30.0.0/26", "10.30.0.128/26"], 26)
        assert proposed == "10.30.0.64/26"

    def test_a_partially_overlapping_candidate_is_skipped(self):
        proposed, _ = first_free_subnet(["10.30.0.0/24"], ["10.30.0.32/27"], 26)
        assert proposed == "10.30.0.64/26"

    def test_a_full_vnet_yields_nothing(self):
        assert first_free_subnet(
            ["10.30.0.0/24"], ["10.30.0.0/25", "10.30.0.128/25"], 26
        ) == (None, None)

    def test_the_whole_address_space_is_a_valid_answer_when_empty(self):
        assert first_free_subnet(["10.30.0.0/24"], [], 24) == ("10.30.0.0/24", "10.30.0.0/24")

    def test_spaces_too_small_for_the_request_are_skipped(self):
        proposed, space = first_free_subnet(["10.30.0.0/28", "10.31.0.0/24"], [], 26)
        assert (proposed, space) == ("10.31.0.0/26", "10.31.0.0/24")

    def test_a_desired_space_filters_the_search(self):
        proposed, space = first_free_subnet(
            ["10.30.0.0/24", "10.31.0.0/24"], [], 26, desired_space="10.31.0.0/24"
        )
        assert (proposed, space) == ("10.31.0.0/26", "10.31.0.0/24")

    def test_a_desired_space_not_in_the_vnet_yields_nothing(self):
        assert first_free_subnet(["10.30.0.0/24"], [], 26, desired_space="10.99.0.0/24") == (
            None,
            None,
        )
