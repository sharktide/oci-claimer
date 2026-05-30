import os
import oci
import time

# Load Oracle configuration from environment variables
config = {
    "user": os.environ["OCI_USER_ID"],
    "fingerprint": os.environ["OCI_FINGERPRINT"],
    "tenancy": os.environ["OCI_TENANCY_ID"],
    "region": os.environ["OCI_REGION"],
    "key_content": os.environ["OCI_PRIVATE_KEY"]
}

def get_or_create_network(network_client, compartment_id):
    """Finds or creates a public subnet and returns its OCID."""
    vcn_name = "AutoClaimVCN"
    subnet_name = "AutoClaimSubnet"
    
    # 1. Look for an existing VCN
    vcns = network_client.list_vcns(compartment_id, display_name=vcn_name).data
    if vcns:
        vcn_id = vcns[0].id
        print(f"Using existing VCN: {vcn_id}")
    else:
        # Create a new VCN
        print("Creating new VCN...")
        vcn_details = oci.core.models.CreateVcnDetails(
            compartment_id=compartment_id,
            display_name=vcn_name,
            cidr_block="10.0.0.0/16"
        )
        vcn_id = network_client.create_vcn(vcn_details).data.id
        time.sleep(5) # Give OCI a moment to provision

    # 2. Look for an existing Subnet inside that VCN
    subnets = network_client.list_subnets(compartment_id, vcn_id=vcn_id, display_name=subnet_name).data
    if subnets:
        subnet_id = subnets[0].id
        print(f"Using existing Subnet: {subnet_id}")
        return subnet_id

    # 3. Create an Internet Gateway so the subnet can route to the web
    print("Creating Internet Gateway...")
    ig_details = oci.core.models.CreateInternetGatewayDetails(
        compartment_id=compartment_id,
        vcn_id=vcn_id,
        is_enabled=True,
        display_name="AutoClaimIG"
    )
    ig_id = network_client.create_internet_gateway(ig_details).data.id

    # 4. Create a Route Table pointing to the Internet Gateway
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
        display_name="AutoClaimRouteTable",
        route_rules=[route_rule]
    )
    rt_id = network_client.create_route_table(rt_details).data.id

    # 5. Create the Public Subnet
    print("Creating Public Subnet...")
    subnet_details = oci.core.models.CreateSubnetDetails(
        compartment_id=compartment_id,
        vcn_id=vcn_id,
        display_name=subnet_name,
        cidr_block="10.0.1.0/24",
        route_table_id=rt_id,
        prohibit_public_ip_on_vnic=False # Ensures a Public IP is allowed
    )
    subnet_id = network_client.create_subnet(subnet_details).data.id
    time.sleep(5)
    return subnet_id

try:
    # Initialize OCI Clients
    compute_client = oci.core.ComputeClient(config)
    network_client = oci.core.VirtualNetworkClient(config)
    
    # Automatically handle VCN and Subnet step
    subnet_ocid = get_or_create_network(network_client, config["tenancy"])
    
    # Configure the A1 Flex server details
    instance_details = oci.core.models.LaunchInstanceDetails(
        compartment_id=config["tenancy"],
        availability_domain=os.environ["OCI_AD_NAME"],
        shape="VM.Standard.A1.Flex",
        shape_config=oci.core.models.LaunchInstanceShapeConfigDetails(
            ocpus=4,
            memory_in_gbs=24
        ),
        source_details=oci.core.models.InstanceSourceViaImageDetails(
            source_type="image",
            image_id=os.environ["OCI_IMAGE_ID"]
        ),
        create_vnic_details=oci.core.models.CreateVnicDetails(
            subnet_id=subnet_ocid,
            assign_public_ip=True
        ),
        display_name="AlwaysFree-A1-ARM"
    )

    print("Attempting to provision Ampere A1 Flex instance...")
    response = compute_client.launch_instance(instance_details)
    print(f"Success! Instance created. ID: {response.data.id}")

except oci.exceptions.ServiceError as e:
    if "Out of host capacity" in str(e):
        print("Status: Out of capacity. Retrying on next run.")
    elif e.status == 429:
        print("Status: Rate limited by Oracle. Slow down your schedule.")
    else:
        print(f"Oracle API Error: {e.message}")
except Exception as e:
    print(f"Unexpected error: {str(e)}")
