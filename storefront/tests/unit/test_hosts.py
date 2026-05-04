"""Unit tests for the hosts table, host CRUD, and adapter host-context join.

Covers:
  - SQLiteClient.upsert_host / get_host / list_hosts
  - SQLiteClient.host_capacity_remaining (capacity bookkeeping)
  - host_csv_importer.upsert_hosts_from_csv
  - ComputeGpuResourceAdapter.to_domain_resource(host_row=...) join behavior
"""
import asyncio
import os
import tempfile
import textwrap

import pytest

from market_storefront.resources import ComputeGpuResourceAdapter
from market_storefront.models.domain_models import (
    ComputeResource,
    GPUModel,
    GpuInterconnect,
    Region,
    VirtualizationType,
)
from market_storefront.utils.sqlite_client import SQLiteClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        yield path
    finally:
        if os.path.exists(path):
            os.unlink(path)


@pytest.fixture
def client(tmp_db):
    return SQLiteClient(db_path=tmp_db)


# ---------------------------------------------------------------------------
# Host CRUD
# ---------------------------------------------------------------------------


class TestHostCrud:
    def test_upsert_and_read(self, client):
        async def _run():
            await client.upsert_host(
                name="ww1",
                cpu_type="Intel Xeon W5-2465X",
                host_cpu_cores=16,
                host_ram_gb=256,
                host_disk_gb=4000,
                host_disk_type="Kingston SFYRD2000G",
                motherboard="ASUS Pro WS W790-ACE",
                total_gpu_count=1,
                gpu_model="RTX 5080",
                gpu_interconnect="pcie_only",
                nic_speed_gbps=10,
                internet_download_mbps=1000,
                internet_upload_mbps=1000,
                static_ip=True,
                open_ports_count=32,
                region="California, US",
                datacenter_grade=True,
            )
            row = await client.get_host(name="ww1")
            assert row is not None
            assert row["cpu_type"] == "Intel Xeon W5-2465X"
            assert row["host_cpu_cores"] == 16
            assert row["static_ip"] is True
            assert row["datacenter_grade"] is True
            assert row["enabled"] is True

        asyncio.run(_run())

    def test_upsert_overwrites(self, client):
        async def _run():
            await client.upsert_host(name="h1", host_ram_gb=128)
            await client.upsert_host(name="h1", host_ram_gb=256)
            row = await client.get_host(name="h1")
            assert row["host_ram_gb"] == 256

        asyncio.run(_run())

    def test_list_hosts_filters_disabled(self, client):
        async def _run():
            await client.upsert_host(name="active1", enabled=True)
            await client.upsert_host(name="dormant", enabled=False)
            active_only = await client.list_hosts(enabled_only=True)
            all_hosts = await client.list_hosts(enabled_only=False)
            assert {h["name"] for h in active_only} == {"active1"}
            assert {h["name"] for h in all_hosts} == {"active1", "dormant"}

        asyncio.run(_run())

    def test_get_missing_host_returns_none(self, client):
        async def _run():
            assert await client.get_host(name="ghost") is None

        asyncio.run(_run())

    def test_attributes_round_trip(self, client):
        async def _run():
            await client.upsert_host(
                name="h2",
                attributes={"tag.datacenter_tier": "tier3", "tag.billing_code": "DC-CA-001"},
            )
            row = await client.get_host(name="h2")
            assert row["attributes"] == {
                "tag.datacenter_tier": "tier3",
                "tag.billing_code": "DC-CA-001",
            }

        asyncio.run(_run())


# ---------------------------------------------------------------------------
# Capacity bookkeeping
# ---------------------------------------------------------------------------


class TestCapacityRemaining:
    def test_full_host_listing_consumes_all(self, client):
        async def _run():
            await client.upsert_host(
                name="h", total_gpu_count=8, host_cpu_cores=192,
                host_ram_gb=2048, host_disk_gb=20000,
            )
            await client.upsert_resource(
                resource_id="r1",
                resource_type="compute.gpu",
                resource_subtype="h200",
                unit="count",
                value=8,
                state="available",
                attributes={"gpu_model": "H200", "sla": 99.0, "region": "California, US",
                            "vm_host": "h", "vcpu_count": 192, "ram_gb": 2048, "disk_gb": 20000},
            )
            cap = await client.host_capacity_remaining(name="h")
            assert cap["limits"] == {"gpu_count": 8, "vcpu_count": 192, "ram_gb": 2048, "disk_gb": 20000}
            assert cap["used"] == {"gpu_count": 8, "vcpu_count": 192, "ram_gb": 2048, "disk_gb": 20000}
            assert all(v == 0 for v in cap["remaining"].values())

        asyncio.run(_run())

    def test_partial_slice_leaves_remainder(self, client):
        async def _run():
            await client.upsert_host(
                name="h", total_gpu_count=2, host_cpu_cores=32,
                host_ram_gb=512, host_disk_gb=8000,
            )
            await client.upsert_resource(
                resource_id="slice1",
                resource_type="compute.gpu",
                resource_subtype="h200",
                unit="count",
                value=1,
                state="available",
                attributes={"gpu_model": "H200", "sla": 95.0, "region": "California, US",
                            "vm_host": "h", "vcpu_count": 16, "ram_gb": 256, "disk_gb": 4000},
            )
            cap = await client.host_capacity_remaining(name="h")
            assert cap["used"] == {"gpu_count": 1, "vcpu_count": 16, "ram_gb": 256, "disk_gb": 4000}
            assert cap["remaining"] == {"gpu_count": 1, "vcpu_count": 16, "ram_gb": 256, "disk_gb": 4000}

        asyncio.run(_run())

    def test_deleted_resources_excluded_from_used(self, client):
        async def _run():
            await client.upsert_host(name="h", total_gpu_count=4, host_cpu_cores=64)
            await client.upsert_resource(
                resource_id="active",
                resource_type="compute.gpu", resource_subtype="h200",
                unit="count", value=2, state="available",
                attributes={"gpu_model": "H200", "sla": 99.0, "region": "California, US",
                            "vm_host": "h", "vcpu_count": 32},
            )
            await client.upsert_resource(
                resource_id="gone",
                resource_type="compute.gpu", resource_subtype="h200",
                unit="count", value=2, state="deleted",
                attributes={"gpu_model": "H200", "sla": 99.0, "region": "California, US",
                            "vm_host": "h", "vcpu_count": 32},
            )
            cap = await client.host_capacity_remaining(name="h")
            assert cap["used"]["gpu_count"] == 2
            assert cap["used"]["vcpu_count"] == 32

        asyncio.run(_run())

    def test_unknown_host_returns_none(self, client):
        async def _run():
            assert await client.host_capacity_remaining(name="ghost") is None

        asyncio.run(_run())


# ---------------------------------------------------------------------------
# CSV importer
# ---------------------------------------------------------------------------


class TestHostsCsvImport:
    def test_imports_two_hosts(self, client, tmp_path):
        csv = tmp_path / "hosts.csv"
        csv.write_text(textwrap.dedent("""\
            name,enabled,cpu_type,host_cpu_cores,host_ram_gb,total_gpu_count,gpu_model,attribute.tag.tier
            h-01,true,AMD EPYC 9654,192,2048,8,H200,tier3
            h-02,true,AMD EPYC 9354,32,512,2,H200,
        """))

        async def _run():
            report = await client.upsert_hosts_from_csv(csv_path=str(csv), dry_run=False)
            assert report["imported_count"] == 2
            assert report["failed_count"] == 0
            row1 = await client.get_host(name="h-01")
            assert row1["cpu_type"] == "AMD EPYC 9654"
            assert row1["host_cpu_cores"] == 192
            assert row1["attributes"] == {"tag.tier": "tier3"}
            row2 = await client.get_host(name="h-02")
            assert row2["host_cpu_cores"] == 32

        asyncio.run(_run())

    def test_dry_run_doesnt_persist(self, client, tmp_path):
        csv = tmp_path / "hosts.csv"
        csv.write_text("name\nh-dry\n")

        async def _run():
            report = await client.upsert_hosts_from_csv(csv_path=str(csv), dry_run=True)
            assert report["imported_count"] == 1
            assert await client.get_host(name="h-dry") is None

        asyncio.run(_run())

    def test_missing_name_column_raises(self, client, tmp_path):
        csv = tmp_path / "bad.csv"
        csv.write_text("cpu_type\nAMD\n")

        async def _run():
            with pytest.raises(ValueError, match="required column: name"):
                await client.upsert_hosts_from_csv(csv_path=str(csv), dry_run=False)

        asyncio.run(_run())


# ---------------------------------------------------------------------------
# Adapter join: host_row merges host context fields onto ComputeResource
# ---------------------------------------------------------------------------


class TestAdapterHostJoin:
    def test_host_row_merges_context_fields(self):
        adapter = ComputeGpuResourceAdapter()
        db_resource = {
            "resource_id": "slice-1",
            "resource_type": "compute.gpu",
            "value": 2,
            "attributes": {
                "gpu_model": "H200",
                "sla": 99.0,
                "region": "California, US",
                "vm_host": "h-01",
                "vcpu_count": 32,
                "ram_gb": 256,
                "disk_gb": 4000,
                "virtualization_type": "vm",
            },
        }
        host_row = {
            "name": "h-01",
            "cpu_type": "AMD EPYC 9654",
            "host_cpu_cores": 192,
            "host_ram_gb": 2048,
            "host_disk_gb": 20000,
            "host_disk_type": "Samsung MZTL3T8HEFK",
            "motherboard": "Supermicro H13DSG-O-CPU",
            "total_gpu_count": 8,
            "gpu_interconnect": "nvswitch",
            "nic_speed_gbps": 200,
            "internet_download_mbps": 10000,
            "internet_upload_mbps": 10000,
            "static_ip": True,
            "open_ports_count": 128,
            "datacenter_grade": True,
        }
        result = adapter.to_domain_resource(db_resource, host_row=host_row)

        assert result.gpu_count == 2
        assert result.vcpu_count == 32
        assert result.ram_gb == 256
        assert result.disk_gb == 4000
        assert result.virtualization_type == VirtualizationType.VM

        assert result.cpu_type == "AMD EPYC 9654"
        assert result.host_cpu_cores == 192
        assert result.host_ram_gb == 2048
        assert result.host_disk_gb == 20000
        assert result.host_disk_type == "Samsung MZTL3T8HEFK"
        assert result.motherboard == "Supermicro H13DSG-O-CPU"
        assert result.total_gpu_count == 8
        assert result.gpu_interconnect == GpuInterconnect.NVSWITCH
        assert result.static_ip is True
        assert result.datacenter_grade is True

    def test_no_host_row_falls_back_to_attrs(self):
        """Legacy / wire-format path: host context fields read from attributes."""
        adapter = ComputeGpuResourceAdapter()
        db_resource = {
            "resource_id": "slice-2",
            "resource_type": "compute.gpu",
            "value": 1,
            "attributes": {
                "gpu_model": "H200",
                "sla": 95.0,
                "region": "California, US",
                "vm_host": "remote-host",
                "vcpu_count": 16,
                "cpu_type": "AMD EPYC 9354",
                "host_cpu_cores": 32,
            },
        }
        result = adapter.to_domain_resource(db_resource)
        assert result.cpu_type == "AMD EPYC 9354"
        assert result.host_cpu_cores == 32
        assert result.vcpu_count == 16

    def test_from_domain_only_writes_slice_fields(self):
        """Host context fields on ComputeResource are NOT written to attributes."""
        adapter = ComputeGpuResourceAdapter()
        resource = ComputeResource(
            gpu_model=GPUModel.H200,
            gpu_count=2,
            sla=99.0,
            region=Region.CALIFORNIA_US,
            vm_host="h-01",
            vcpu_count=32,
            ram_gb=256,
            disk_gb=4000,
            virtualization_type=VirtualizationType.VM,
            # Host context — these should NOT end up in attributes
            cpu_type="AMD EPYC 9654",
            host_cpu_cores=192,
            motherboard="Supermicro H13DSG-O-CPU",
        )
        db_row = adapter.from_domain_resource(resource, resource_id="r-1", state="available")
        attrs = db_row["attributes"]

        # Slice fields present
        assert attrs["vcpu_count"] == 32
        assert attrs["ram_gb"] == 256
        assert attrs["disk_gb"] == 4000
        assert attrs["virtualization_type"] == "vm"
        assert attrs["vm_host"] == "h-01"

        # Host context fields absent
        assert "cpu_type" not in attrs
        assert "host_cpu_cores" not in attrs
        assert "motherboard" not in attrs


# ---------------------------------------------------------------------------
# Capacity enforcement on upsert_resource
# ---------------------------------------------------------------------------


from market_storefront.utils.capacity import CapacityExceededError


class TestCapacityEnforcement:
    def _attrs(self, host: str, vcpu: int = 16, ram: int = 256, disk: int = 4000) -> dict:
        return {
            "gpu_model": "H200", "sla": 99.0, "region": "California, US",
            "vm_host": host, "vcpu_count": vcpu, "ram_gb": ram, "disk_gb": disk,
        }

    def test_first_slice_within_capacity_passes(self, client):
        async def _run():
            await client.upsert_host(
                name="h", total_gpu_count=4, host_cpu_cores=64,
                host_ram_gb=512, host_disk_gb=8000,
            )
            # 1 GPU / 16 vCPU / 256 RAM / 4 TB on a 4-GPU / 64-core / 512 GB / 8 TB host.
            await client.upsert_resource(
                resource_id="s1",
                resource_type="compute.gpu",
                resource_subtype="h200",
                unit="count", value=1, state="available",
                attributes=self._attrs("h"),
            )
            cap = await client.host_capacity_remaining(name="h")
            assert cap["used"]["gpu_count"] == 1

        asyncio.run(_run())

    def test_second_slice_within_remaining_capacity_passes(self, client):
        async def _run():
            await client.upsert_host(
                name="h", total_gpu_count=4, host_cpu_cores=64,
                host_ram_gb=512, host_disk_gb=8000,
            )
            await client.upsert_resource(
                resource_id="s1", resource_type="compute.gpu",
                resource_subtype="h200", unit="count", value=2, state="available",
                attributes=self._attrs("h", vcpu=32, ram=256, disk=4000),
            )
            await client.upsert_resource(
                resource_id="s2", resource_type="compute.gpu",
                resource_subtype="h200", unit="count", value=2, state="available",
                attributes=self._attrs("h", vcpu=32, ram=256, disk=4000),
            )
            cap = await client.host_capacity_remaining(name="h")
            assert cap["remaining"] == {"gpu_count": 0, "vcpu_count": 0, "ram_gb": 0, "disk_gb": 0}

        asyncio.run(_run())

    def test_oversubscribing_gpu_count_rejected(self, client):
        async def _run():
            await client.upsert_host(name="h", total_gpu_count=2, host_cpu_cores=64)
            await client.upsert_resource(
                resource_id="s1", resource_type="compute.gpu",
                resource_subtype="h200", unit="count", value=2, state="available",
                attributes=self._attrs("h", vcpu=32),
            )
            with pytest.raises(CapacityExceededError, match="gpu_count"):
                await client.upsert_resource(
                    resource_id="s2", resource_type="compute.gpu",
                    resource_subtype="h200", unit="count", value=1, state="available",
                    attributes=self._attrs("h", vcpu=16),
                )

        asyncio.run(_run())

    def test_oversubscribing_ram_rejected(self, client):
        async def _run():
            await client.upsert_host(
                name="h", total_gpu_count=4, host_cpu_cores=64, host_ram_gb=128,
            )
            await client.upsert_resource(
                resource_id="s1", resource_type="compute.gpu",
                resource_subtype="h200", unit="count", value=1, state="available",
                attributes=self._attrs("h", ram=100),
            )
            with pytest.raises(CapacityExceededError, match="ram_gb"):
                await client.upsert_resource(
                    resource_id="s2", resource_type="compute.gpu",
                    resource_subtype="h200", unit="count", value=1, state="available",
                    attributes=self._attrs("h", ram=64),
                )

        asyncio.run(_run())

    def test_reimport_same_resource_is_idempotent(self, client):
        """Re-upserting the same resource_id excludes itself from the capacity sum."""
        async def _run():
            await client.upsert_host(name="h", total_gpu_count=2)
            attrs = self._attrs("h")
            await client.upsert_resource(
                resource_id="s1", resource_type="compute.gpu",
                resource_subtype="h200", unit="count", value=2, state="available",
                attributes=attrs,
            )
            # Re-upsert with same id and full host gpu_count — should pass.
            await client.upsert_resource(
                resource_id="s1", resource_type="compute.gpu",
                resource_subtype="h200", unit="count", value=2, state="available",
                attributes=attrs,
            )
            cap = await client.host_capacity_remaining(name="h")
            assert cap["used"]["gpu_count"] == 2

        asyncio.run(_run())

    def test_unknown_host_passes_through(self, client):
        """Resources pointing at hosts the operator hasn't registered are not gated."""
        async def _run():
            # No upsert_host call. Resource references vm_host="never-registered".
            await client.upsert_resource(
                resource_id="remote", resource_type="compute.gpu",
                resource_subtype="h200", unit="count", value=64, state="available",
                attributes=self._attrs("never-registered", vcpu=512, ram=4096, disk=80000),
            )
            # Did not raise.

        asyncio.run(_run())

    def test_no_vm_host_passes_through(self, client):
        """Resources without vm_host (legacy) are not gated."""
        async def _run():
            attrs = {"gpu_model": "H200", "sla": 99.0, "region": "California, US"}
            await client.upsert_resource(
                resource_id="legacy", resource_type="compute.gpu",
                resource_subtype="h200", unit="count", value=4, state="available",
                attributes=attrs,
            )

        asyncio.run(_run())

    def test_deleted_state_skips_capacity_check(self, client):
        """Soft-deleting a slice doesn't run the capacity gate."""
        async def _run():
            await client.upsert_host(name="h", total_gpu_count=1)
            # Pre-fill the host.
            await client.upsert_resource(
                resource_id="s1", resource_type="compute.gpu",
                resource_subtype="h200", unit="count", value=1, state="available",
                attributes=self._attrs("h"),
            )
            # Now mark it deleted with the same gpu_count — gate skipped.
            await client.upsert_resource(
                resource_id="s1", resource_type="compute.gpu",
                resource_subtype="h200", unit="count", value=1, state="deleted",
                attributes=self._attrs("h"),
            )

        asyncio.run(_run())

    def test_csv_import_surfaces_capacity_error_per_row(self, client, tmp_path):
        """An over-committed slice in CSV becomes a row-level error, not a fatal."""
        hosts = tmp_path / "hosts.csv"
        hosts.write_text(
            "name,total_gpu_count,host_cpu_cores,host_ram_gb,host_disk_gb\nh,2,32,256,4000\n"
        )
        # Two slices each demanding 2 GPUs — the second over-commits by 2.
        resources = tmp_path / "resources.csv"
        resources.write_text(
            "resource_id,resource_type,unit,value,state,attribute.gpu_model,attribute.sla,"
            "attribute.region,attribute.vm_host,attribute.vcpu_count,attribute.ram_gb,"
            "attribute.disk_gb\n"
            "ok,compute.gpu,count,2,available,H200,99.0,\"California, US\",h,16,128,2000\n"
            "bad,compute.gpu,count,2,available,H200,99.0,\"California, US\",h,16,128,2000\n"
        )

        async def _run():
            await client.upsert_hosts_from_csv(csv_path=str(hosts), dry_run=False)
            report = await client.upsert_resources_from_csv(csv_path=str(resources), dry_run=False)
            # The "ok" row imports; the "bad" row fails capacity but doesn't crash.
            assert report["imported_count"] == 1
            assert report["failed_count"] == 1
            bad_rows = [r for r in report["rows"] if not r["imported"]]
            assert len(bad_rows) == 1
            assert any("over-committed" in e for e in bad_rows[0]["errors"])

        asyncio.run(_run())
