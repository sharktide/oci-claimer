import os
import oci

# Load Oracle configuration from environment variables
config = {
    "user": os.environ["OCI_USER_ID"],
    "fingerprint": os.environ["OCI_FINGERPRINT"],
    "tenancy": os.environ["OCI_TENANCY_ID"],
    "region": os.environ["OCI_REGION"],
    "key_content": os.environ["OCI_PRIVATE_KEY"]
}

try:
    # Initialize the compute client
    compute_client = oci.core.ComputeClient(config)
    
    # Configure the A1 Flex server details
    instance_details = oci.core.models.LaunchInstanceDetails(
        compartment_id=config["tenancy"],
        availability_domain=os.environ["OCI_AD_NAME"], # e.g., "UvXg:US-ASHBURN-AD-1"
        shape="VM.Standard.A1.Flex",
        shape_config=oci.core.models.LaunchInstanceShapeConfigDetails(
            ocpus=4,
            memory_in_gbs=24
        ),
        source_details=oci.core.models.InstanceSourceViaImageDetails(
            source_type="image",
            image_id=os.environ["OCI_IMAGE_ID"] # Ubuntu/Oracle Linux image ID
        ),
        create_vnic_details=oci.core.models.CreateVnicDetails(
            subnet_id=os.environ["OCI_SUBNET_ID"],
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
