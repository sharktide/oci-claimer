import os
import time
import oci
from functools import partial

# Force flush for safety
print = partial(print, flush=True)

config = {
    "user": os.environ["OCI_USER_ID"],
    "fingerprint": os.environ["OCI_FINGERPRINT"],
    "tenancy": os.environ["OCI_TENANCY_ID"],
    "region": os.environ["OCI_REGION"],
    "key_content": os.environ["OCI_PRIVATE_KEY"]
}

# Load SSH key
with open("id_ed25519.pub", "r") as f:
    SSH_PUBLIC_KEY = f.read().strip()


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
        vcn_id = network_client.create_vcn(
            oci.core.models.CreateVcnDetails(
                compartment_id=compartment_id,
                display_name=vcn_name,
                cidr_block="10.30.0.0/16"
            )
        ).data.id
        time.sleep(8)

    subnets = network_client.list_subnets(
        compartment_id,
        vcn_id=vcn_id,
        display_name=subnet_name
    ).data

    if subnets:
        return subnets[0].id

    ig_id = network_client.create_internet_gateway(
        oci.core.models.CreateInternetGatewayDetails(
            compartment_id=compartment_id,
            vcn_id=vcn_id,
            is_enabled=True,
            display_name="AutoClaimIG-ManualMulti"
        )
    ).data.id

    rt_id = network_client.create_route_table(
        oci.core.models.CreateRouteTableDetails(
            compartment_id=compartment_id,
            vcn_id=vcn_id,
            display_name="AutoClaimRouteTable-ManualMulti",
            route_rules=[
                oci.core.models.RouteRule(
                    cidr_block="0.0.0.0/0",
                    destination="0.0.0.0/0",
                    destination_type="CIDR_BLOCK",
                    network_entity_id=ig_id
                )
            ]
        )
    ).data.id

    subnet_id = network_client.create_subnet(
        oci.core.models.CreateSubnetDetails(
            compartment_id=compartment_id,
            vcn_id=vcn_id,
            display_name=subnet_name,
            cidr_block="10.30.1.0/24",
            route_table_id=rt_id,
            prohibit_public_ip_on_vnic=False
        )
    ).data.id

    time.sleep(8)
    return subnet_id


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
            ocpus=2.0,
            memory_in_gbs=12.0
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
        line = ""

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

                print("\n====================================")
                print("INSTANCE CREATED SUCCESSFULLY")
                print("====================================")
                print(f"AD: {target_ad}")
                print(f"INSTANCE ID: {response.data.id}")
                print("====================================")

                instance_created = True
                break

            except oci.exceptions.ServiceError as e:
                if "Out of host capacity" in str(e):
                    line += str(i)   # 1 2 3

                elif e.status == 429:
                    line += "R"

                else:
                    line += "E"

        # IMPORTANT: newline forces GitHub Actions to flush logs
        print(line + "!", flush=True)

        if instance_created:
            break

        time.sleep(60)

    except Exception:
        print("X!", flush=True)
        time.sleep(60)
