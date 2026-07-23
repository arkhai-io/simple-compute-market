"""Ansible implementation of the provider-neutral fulfillment contract."""
from __future__ import annotations
import dataclasses
from typing import TYPE_CHECKING, Any, Callable
from compute_provisioning.contracts import ExecutorActionEnvelope
from market_fulfillment import (
    FulfillmentCreateFailedError, FulfillmentProvider, FulfillmentResult,
    FulfillmentStatusFailedError, FulfillmentTeardownFailedError,
    ProviderConfigInvalidError, ProviderOperationState, ProviderStatus,
    SettlementResource, SettlementResult, VersionedEnvelope,
)
from vm_provisioning_adapter.models.jobs_model import AnsibleJobParams
from vm_provisioning_adapter.models.fulfillment_model import (
    AnsibleFulfillmentMetadata, AnsiblePreparedOperation, VmFulfillmentRequirements,
)
if TYPE_CHECKING:
    from compute_provisioning_service.services.async_job_queue import AsyncJobQueue
    from vm_provisioning_adapter.services.job_service import AnsibleJobService

_CREATE_KIND='vm.ansible.create.v1'; _TEARDOWN_KIND='vm.ansible.teardown.v1'
_JOB_STATUS_TO_OPERATION_STATE={'queued':ProviderOperationState.pending,'running':ProviderOperationState.pending,'succeeded':ProviderOperationState.succeeded,'failed':ProviderOperationState.failed,'cancelled':ProviderOperationState.failed}

class AnsibleFulfillmentProvider(FulfillmentProvider):
    def __init__(self, *, job_service:'AnsibleJobService', job_queue_provider:Callable[[], 'AsyncJobQueue'], resource_pool_service:Any|None=None) -> None:
        self._job_service=job_service; self._job_queue_provider=job_queue_provider
    @staticmethod
    def _pool_config(pool_config:dict[str,Any]) -> tuple[str,dict[str,Any]]:
        playbook=pool_config.get('playbook_path')
        if not isinstance(playbook,str) or not playbook: raise ProviderConfigInvalidError('pool has no playbook_path configured')
        return playbook,dict(pool_config.get('extra_vars') or {})
    @staticmethod
    def _vm_host(resource:SettlementResource)->str:
        value=resource.attributes.get('vm_host')
        if not isinstance(value,str) or not value.strip(): raise ProviderConfigInvalidError('selected VM settlement resource requires a non-empty vm_host attribute')
        return value
    def _validate_extra_vars(self, params:AnsibleJobParams, extra:dict[str,Any])->None:
        collisions=sorted(self._job_service.reserved_var_keys(params).intersection(extra))
        if collisions: raise ProviderConfigInvalidError('provider extra_vars override reserved job variables: '+', '.join(collisions))
    def prepare_create(self, request:VersionedEnvelope[Any], resource:SettlementResource, pool_config:dict[str,Any])->VersionedEnvelope[Any]:
        try: req=VmFulfillmentRequirements.model_validate(request.payload)
        except Exception as exc: raise ProviderConfigInvalidError(f'invalid VM fulfillment requirements: {exc}') from exc
        playbook,extra=self._pool_config(pool_config)
        params=AnsibleJobParams(vm_host=self._vm_host(resource),vm_action='create',vm_target=req.vm_target,image_setup_type=req.image_setup_type,vm_ram=req.vm_ram,vm_vcpus=req.vm_vcpus,vm_disk_size=req.vm_disk_size,vm_os_variant=req.vm_os_variant,ssh_pubkey=req.ssh_pubkey,gpu_provisioned=req.gpu_provisioned,vm_gpu_count=req.vm_gpu_count,vm_gpu_device=req.vm_gpu_device,vm_gpu_devices=req.vm_gpu_devices,vm_gpu_partition_size=req.vm_gpu_partition_size,escrow_uid=request.payload.get('capacity_reservation_id') if isinstance(request.payload,dict) else None,playbook_path=playbook)
        # The orchestrator's durable id is carried in the envelope payload when needed;
        # adapter dispatch requires it and validates it below.
        capacity_id=(request.payload.get('capacity_reservation_id') if isinstance(request.payload,dict) else None) or resource.attributes.get('capacity_reservation_id')
        if not capacity_id: raise ProviderConfigInvalidError('fulfillment request requires capacity_reservation_id')
        params.escrow_uid=str(capacity_id); self._validate_extra_vars(params,extra); params=dataclasses.replace(params,provider_extra_vars=extra)
        payload=AnsiblePreparedOperation(capacity_reservation_id=str(capacity_id),action='create',parameters=dataclasses.asdict(params))
        return VersionedEnvelope(kind=_CREATE_KIND,schema_version=1,payload=payload.model_dump(mode='json'))
    async def dispatch_create(self, prepared:VersionedEnvelope[Any])->FulfillmentResult:
        try:
            if prepared.kind!=_CREATE_KIND or prepared.schema_version!=1: raise ProviderConfigInvalidError('unsupported Ansible create envelope')
            op=AnsiblePreparedOperation.model_validate(prepared.payload); params=AnsibleJobParams(**op.parameters)
            contract=ExecutorActionEnvelope(capacity_reservation_id=op.capacity_reservation_id,deal_ref={},executor_kind='vm',action_kind='create',idempotency_key=f'{op.capacity_reservation_id}:create',parameters=op.parameters)
            response=await self._job_service.submit(params,self._job_queue_provider(),contract=contract)
            metadata=AnsibleFulfillmentMetadata(create_job_id=response.job_id,current_job_id=response.job_id,vm_host=params.vm_host,vm_target=params.vm_target or '',operation='create')
            return FulfillmentResult(metadata.model_dump(mode='json'))
        except ProviderConfigInvalidError: raise
        except Exception as exc: raise FulfillmentCreateFailedError(str(exc)) from exc
    def prepare_teardown(self, settlement_result:SettlementResult, pool_config:dict[str,Any])->VersionedEnvelope[Any]:
        try: metadata=AnsibleFulfillmentMetadata.model_validate(settlement_result.provider_metadata)
        except Exception as exc: raise ProviderConfigInvalidError(f'invalid Ansible fulfillment metadata: {exc}') from exc
        playbook,extra=self._pool_config(pool_config)
        params=AnsibleJobParams(vm_host=metadata.vm_host,vm_action='vm_remove',vm_target=metadata.vm_target,escrow_uid=settlement_result.capacity_reservation_id,playbook_path=playbook)
        self._validate_extra_vars(params,extra); params=dataclasses.replace(params,provider_extra_vars=extra)
        payload=AnsiblePreparedOperation(capacity_reservation_id=settlement_result.capacity_reservation_id,action='teardown',parameters=dataclasses.asdict(params))
        return VersionedEnvelope(kind=_TEARDOWN_KIND,schema_version=1,payload=payload.model_dump(mode='json'))
    async def dispatch_teardown(self, prepared:VersionedEnvelope[Any])->FulfillmentResult:
        try:
            if prepared.kind!=_TEARDOWN_KIND or prepared.schema_version!=1: raise ProviderConfigInvalidError('unsupported Ansible teardown envelope')
            op=AnsiblePreparedOperation.model_validate(prepared.payload); params=AnsibleJobParams(**op.parameters)
            contract=ExecutorActionEnvelope(capacity_reservation_id=op.capacity_reservation_id,deal_ref={},executor_kind='vm',action_kind='teardown',idempotency_key=f'{op.capacity_reservation_id}:teardown',parameters=op.parameters)
            response=await self._job_service.submit(params,self._job_queue_provider(),contract=contract)
            return FulfillmentResult({'teardown_job_id':response.job_id,'current_job_id':response.job_id,'operation':'teardown'})
        except ProviderConfigInvalidError: raise
        except Exception as exc: raise FulfillmentTeardownFailedError(str(exc)) from exc
    async def get_status(self, capacity_reservation_id:str, resource:SettlementResource, provider_metadata:dict[str,Any])->ProviderStatus:
        try: metadata=AnsibleFulfillmentMetadata.model_validate(provider_metadata); job_id=metadata.current_job_id
        except Exception as exc: return ProviderStatus(ProviderOperationState.unknown,f'invalid provider metadata: {exc}')
        try: job=self._job_service.get_job(job_id)
        except LookupError: return ProviderStatus(ProviderOperationState.unknown,f'job {job_id} not found')
        except Exception as exc: raise FulfillmentStatusFailedError(str(exc)) from exc
        return ProviderStatus(_JOB_STATUS_TO_OPERATION_STATE.get(job.status,ProviderOperationState.unknown),job.error)
