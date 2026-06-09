import requests
import urllib3
import json

# Suppress SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- Configuration ---
VC_HOST = "vc-wld01-a.site-a.vcf.lab"
VC_USER = "administrator@WLD.SSO"
PASS_FILE = "/home/holuser/creds.txt"

CATEGORY_NAME = "infrastructure"
# Mapping Tag Name -> List of Host FQDNs or Short Names
ASSIGNMENTS = {
    "production": ["esx-05a.site-a.vcf.lab"],
    "disaster-recovery": ["esx-06a.site-a.vcf.lab", "esx-07a.site-a.vcf.lab"]
}

def get_vc_session():
    """Authenticates and returns a clean session token."""
    try:
        with open(PASS_FILE, 'r') as f:
            password = f.read().strip()
        url = f"https://{VC_HOST}/api/session"
        res = requests.post(url, auth=(VC_USER, password), verify=False)
        res.raise_for_status()
        return res.json().replace('"', '')
    except Exception as e:
        print(f"Authentication Error: {e}")
        exit(1)

def get_host_id(token, host_name):
    """Lists all hosts and matches name manually (case-insensitive)."""
    url = f"https://{VC_HOST}/api/vcenter/host"
    headers = {"vmware-api-session-id": token}
    res = requests.get(url, headers=headers, verify=False)
    if res.status_code != 200:
        return None
    
    hosts_data = res.json()
    target = host_name.lower().strip()
    for host in hosts_data:
        vcenter_name = host.get('name', '').lower()
        if target == vcenter_name or vcenter_name.startswith(target):
            return host.get('host')
    return None

def create_or_get_category(token, name):
    """Finds or creates category using v9 flattened JSON."""
    headers = {"vmware-api-session-id": token, "Content-Type": "application/json"}
    url = f"https://{VC_HOST}/api/cis/tagging/category"
    
    res = requests.get(url, headers=headers, verify=False)
    data = res.json()
    cat_ids = data.get('Value', []) if isinstance(data, dict) else data
    
    if isinstance(cat_ids, list):
        for cid in cat_ids:
            d_res = requests.get(f"{url}/{cid}", headers=headers, verify=False)
            d_val = d_res.json().get('Value', {}) if isinstance(d_res.json(), dict) else d_res.json()
            if d_val.get('name') == name:
                print(f"Category '{name}' verified.")
                return cid

    print(f"Creating Category: {name}")
    body = {
        "name": name,
        "description": "Infra tags",
        "cardinality": "MULTIPLE",
        "associable_types": ["HostSystem", "VirtualMachine"]
    }
    res = requests.post(url, json=body, headers=headers, verify=False)
    res.raise_for_status()
    res_data = res.json()
    return res_data.get('Value') if isinstance(res_data, dict) else res_data

def create_or_get_tag(token, tag_name, cat_id):
    """Finds or creates tag using v9 flattened JSON."""
    headers = {"vmware-api-session-id": token, "Content-Type": "application/json"}
    url = f"https://{VC_HOST}/api/cis/tagging/tag"
    
    res = requests.get(url, headers=headers, verify=False)
    data = res.json()
    tag_ids = data.get('Value', []) if isinstance(data, dict) else data
    
    if isinstance(tag_ids, list):
        for tid in tag_ids:
            d_res = requests.get(f"{url}/{tid}", headers=headers, verify=False)
            d_val = d_res.json().get('Value', {}) if isinstance(d_res.json(), dict) else d_res.json()
            if d_val.get('name') == tag_name and d_val.get('category_id') == cat_id:
                print(f"Tag '{tag_name}' verified.")
                return tid

    print(f"Creating Tag: {tag_name}")
    body = {"name": tag_name, "category_id": cat_id, "description": tag_name}
    res = requests.post(url, json=body, headers=headers, verify=False)
    res.raise_for_status()
    res_data = res.json()
    return res_data.get('Value') if isinstance(res_data, dict) else res_data

def attach_tag(token, tag_id, host_id):
    """Attaches tag using standard path with legacy fallback."""
    headers = {"vmware-api-session-id": token, "Content-Type": "application/json"}
    body = {
        "tag_id": tag_id.strip().replace('"', ''),
        "object_id": {"type": "HostSystem", "id": host_id.strip().replace('"', '')}
    }
    
    # Try modern API path
    url = f"https://{VC_HOST}/api/cis/tagging/tag-association?action=attach"
    res = requests.post(url, json=body, headers=headers, verify=False)
    
    # If 404, try legacy REST path
    if res.status_code == 404:
        url = f"https://{VC_HOST}/rest/com/vmware/cis/tagging/tag-association?~action=attach"
        res = requests.post(url, json=body, headers=headers, verify=False)

    if res.status_code < 300 or (res.status_code == 400 and "already_exists" in res.text):
        return True
    
    print(f"  - Attach Error: {res.status_code} - {res.text}")
    return False

def main():
    try:
        token = get_vc_session()
        print("Successfully authenticated.")

        cat_id = create_or_get_category(token, CATEGORY_NAME)
        
        for tag_name, host_list in ASSIGNMENTS.items():
            tag_id = create_or_get_tag(token, tag_name, cat_id)
            for h_name in host_list:
                h_id = get_host_id(token, h_name)
                if h_id:
                    print(f"Applying {tag_name} to {h_name}...")
                    if attach_tag(token, tag_id, h_id):
                        print("    - Success!")
                else:
                    print(f"    - Error: Host '{h_name}' not found.")
        print("\nAll operations completed successfully.")
    except Exception as e:
        print(f"Critical Script Error: {e}")

if __name__ == "__main__":
    main()
