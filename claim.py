import os
import time
import oci
from functools import partial

# flush prints immediately
print = partial(print, flush=True)

config = {
    "user": os.environ["OCI_USER_ID"],
    "fingerprint": os.environ["OCI_FINGERPRINT"],
    "tenancy": os.environ["OCI_TENANCY_ID"],
    "region": os.environ["OCI_REGION"],
    "key_content": os.environ["OCI_PRIVATE_KEY"]
}

# Load SSH public key
with open("id_ed25519.pub", "r") as f:
    SSH_PUBLIC_KEY = f.read().strip()


def heartbeat(msg):
    print(msg, end="", flush=True)


def get_or_create_network(network_client, compartment_id):
    vcn_name = "AutoClaimVCN-ManualMulti"
    subnet_name = "AutoClaimSubnet-ManualMulti"

    vcns = network_client.list_vcns(
        compartment_id,
        display_name=vcn_name
    ).data

    if vcns:
        vcn_id = vcns[0].id
    else:
        vcn_details = oci.core.models.CreateVcnDetails(
            compartment_id=compartment_id,
            display_name=vcn_name,
            cidr_block="10.30.0.0/16"
        )
        vcn_id = network_client.create_vcn(vcn_details).data.id
        time.sleep(8)

    subnets = network_client.list_subnets(
        compartment_id,
        vcn_id=vcn_id,
        display_name=subnet_name
    ).data

    if subnets:
        return subnets[0].id

    ig_details = oci.core.models.CreateInternetGatewayDetails(
        compartment_id=compartment_id,
        vcn_id=vcn_id,
        is_enabled=True,
        display_name="AutoClaimIG-ManualMulti"
    )
    ig_id = network_client.create_internet_gateway(ig_details).data.id

    route_rule = oci.core.models.RouteRule(
        cidr_block="0.0.0.0/0",
        destination="0.0.0.0/0",
        destination_type="CIDR_BLOCK",
        network_entity_id=ig_id
    )

    rt_details = oci.core.models.CreateRouteTableDetails(
        compartment_id=compartment_id,
        vcn_id=vcn_id,
        display_name="AutoClaimRouteTable-ManualMulti",
        route_rules=[route_rule]
    )
    rt_id = network_client.create_route_table(rt_details).data.id

    subnet_details = oci.core.models.CreateSubnetDetails(
        compartment_id=compartment_id,
        vcn_id=vcn_id,
        display_name=subnet_name,
        cidr_block="10.30.1.0/24",
        route_table_id=rt_id,
        prohibit_public_ip_on_vnic=False
    )

    return network_client.create_subnet(subnet_details).data.id


while True:
    try:
        raw_ad_secret = os.environ.get("OCI_AD_NAME", "")
        if not raw_ad_secret:
            raise ValueError("OCI_AD_NAME missing")

        ad_names = [a.strip() for a in raw_ad_secret.split(",") if a.strip()]

        compute_client = oci.core.ComputeClient(config)
        network_client = oci.core.VirtualNetworkClient(config)

        subnet_ocid = get_or_create_network(network_client, config["tenancy"])

        shape_config = oci.core.models.LaunchInstanceShapeConfigDetails(
            ocpus=4.0,
            memory_in_gbs=24.0
        )

        source_details = oci.core.models.InstanceSourceViaImageDetails(
            source_type="image",
            image_id=os.environ["OCI_IMAGE_ID"].strip()
        )

        vnic_details = oci.core.models.CreateVnicDetails(
            subnet_id=subnet_ocid,
            assign_public_ip=True
        )

        metadata = {
            "ssh_authorized_keys": SSH_PUBLIC_KEY
        }

        instance_created = False

        for i, target_ad in enumerate(ad_names, start=1):
            try:
                instance_details = oci.core.models.LaunchInstanceDetails(
                    compartment_id=config["tenancy"],
                    availability_domain=target_ad,
                    shape="VM.Standard.A1.Flex",
                    shape_config=shape_config,
                    source_details=source_details,
                    create_vnic_details=vnic_details,
                    display_name="AlwaysFree-A1-ARM",
                    metadata=metadata
                )

                response = compute_client.launch_instance(instance_details)

                print("\n")
                print("====================================")
                print("INSTANCE CREATED SUCCESSFULLY")
                print("====================================")
                print(f"AD: {target_ad}")
                print(f"ID: {response.data.id}")
                print("====================================")

                instance_created = True
                break

            except oci.exceptions.ServiceError as e:
                if "Out of host capacity" in str(e):
                    heartbeat(str(i))   # 1,2,3...

                elif e.status == 429:
                    heartbeat("R")

                else:
                    heartbeat("E")

        if instance_created:
            break

        heartbeat("!")
        time.sleep(60)

    except Exception:
        heartbeat("X")
        time.sleep(60)
