import os
import time
import oci

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


def get_or_create_network(network_client, compartment_id):
    vcn_name = "AutoClaimVCN-ManualMulti"
    subnet_name = "AutoClaimSubnet-ManualMulti"

    # Fetch existing VCN
    vcns = network_client.list_vcns(
        compartment_id,
        display_name=vcn_name
    ).data

    if vcns:
        vcn_id = vcns[0].id
        print(f"Using existing VCN: {vcn_id}")
    else:
        print("Creating new VCN...")
        vcn_details = oci.core.models.CreateVcnDetails(
            compartment_id=compartment_id,
            display_name=vcn_name,
            cidr_block="10.30.0.0/16"
        )

        vcn_id = network_client.create_vcn(vcn_details).data.id
        time.sleep(8)

    # Fetch existing subnet
    subnets = network_client.list_subnets(
        compartment_id,
        vcn_id=vcn_id,
        display_name=subnet_name
    ).data

    if subnets:
        subnet_id = subnets[0].id
        print(f"Using existing Subnet: {subnet_id}")
        return subnet_id

    print("Creating Internet Gateway...")
    ig_details = oci.core.models.CreateInternetGatewayDetails(
        compartment_id=compartment_id,
        vcn_id=vcn_id,
        is_enabled=True,
        display_name="AutoClaimIG-ManualMulti"
    )

    ig_id = network_client.create_internet_gateway(ig_details).data.id

    print("Creating Route Table...")
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

    print("Creating Public Subnet...")
    subnet_details = oci.core.models.CreateSubnetDetails(
        compartment_id=compartment_id,
        vcn_id=vcn_id,
        display_name=subnet_name,
        cidr_block="10.30.1.0/24",
        route_table_id=rt_id,
        prohibit_public_ip_on_vnic=False
    )

    subnet_id = network_client.create_subnet(subnet_details).data.id
    time.sleep(8)

    return subnet_id


while True:
    try:
        print(
            f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] "
            "Starting Oracle capacity check..."
        )

        raw_ad_secret = os.environ.get("OCI_AD_NAME", "")

        if not raw_ad_secret:
            raise ValueError("OCI_AD_NAME secret is empty or missing.")

        ad_names = [
            ad.strip()
            for ad in raw_ad_secret.split(",")
            if ad.strip()
        ]

        print(f"Checking {len(ad_names)} availability domains:")
        print(ad_names)

        # OCI clients
        compute_client = oci.core.ComputeClient(config)
        network_client = oci.core.VirtualNetworkClient(config)

        # Ensure network exists
        subnet_ocid = get_or_create_network(
            network_client,
            config["tenancy"]
        )

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

        for target_ad in ad_names:
            print(f"\n---> Testing capacity in: {target_ad} <---")

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

            try:
                response = compute_client.launch_instance(
                    instance_details
                )

                print("\n====================================")
                print("INSTANCE CREATED SUCCESSFULLY")
                print("====================================")
                print(f"Availability Domain: {target_ad}")
                print(f"Instance ID: {response.data.id}")
                print("SSH key injected from id_ed25519.pub")
                print("====================================")

                instance_created = True
                break

            except oci.exceptions.ServiceError as e:
                if "Out of host capacity" in str(e):
                    print(f"Out of host capacity in {target_ad}")

                elif e.status == 429:
                    print("Oracle rate limit hit (429).")
                    break

                else:
                    print(
                        f"Oracle API Error in {target_ad}: "
                        f"{e.status} - {e.message}"
                    )

        if instance_created:
            print("Exiting because instance was successfully created.")
            break

        print("\nNo capacity available. Sleeping 60 seconds...")

    except Exception as e:
        print(f"Unexpected Script Execution Fault: {e}")

    time.sleep(60)
