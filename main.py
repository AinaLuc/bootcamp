from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import subprocess
import os

app = FastAPI()

# Configurable Paths
WORDPRESS_DIR = os.getenv("WORDPRESS_DIR", "/var/www/")
NGINX_CONFIG_PATH = os.getenv("NGINX_CONFIG_PATH", "/etc/nginx/sites-available/")
NGINX_ENABLED_PATH = os.getenv("NGINX_ENABLED_PATH", "/etc/nginx/sites-enabled/")
PHP_FPM_SOCK = os.getenv("PHP_FPM_SOCK", "/run/php/php7.4-fpm.sock")

VERIFICATION_TXT = "wp-verify"  # Required TXT record for verification
SERVER_IP = "172.190.115.194"  # Required A record IP

class InstallRequest(BaseModel):
    domain: str

def check_txt_record(domain: str) -> bool:
    """Check if the domain has the required TXT record."""
    try:
        result = subprocess.run(["dig", "+short", "TXT", domain], capture_output=True, text=True)
        return VERIFICATION_TXT in result.stdout
    except Exception as e:
        print(f"Error checking TXT record: {e}")
        return False

def check_a_record(domain: str) -> bool:
    """Check if the domain A record points to the required IP."""
    try:
        result = subprocess.run(["dig", "+short", domain], capture_output=True, text=True)
        return SERVER_IP in result.stdout.strip().split("\n")
    except Exception as e:
        print(f"Error checking A record: {e}")
        return False

def install_wordpress(domain: str):
    """Installs WordPress for a given domain if verified."""
    domain_path = os.path.join(WORDPRESS_DIR, domain)

    if os.path.exists(domain_path):
        raise HTTPException(status_code=400, detail="Domain already installed.")

    if not check_txt_record(domain):
        raise HTTPException(
            status_code=400,
            detail=f"Domain is not verified. Add TXT record '{VERIFICATION_TXT}' and retry."
        )

    if not check_a_record(domain):
        raise HTTPException(
            status_code=400,
            detail=f"A record not set. Please point '{domain}' to {SERVER_IP} and retry."
        )

    # Create directory and install WordPress
    os.makedirs(domain_path, exist_ok=True)
    subprocess.run(["wget", "https://wordpress.org/latest.tar.gz", "-P", domain_path], check=True)
    subprocess.run(["tar", "-xzf", f"{domain_path}/latest.tar.gz", "-C", domain_path, "--strip-components=1"], check=True)
    os.remove(f"{domain_path}/latest.tar.gz")

    # Set correct permissions
    subprocess.run(["chown", "-R", "www-data:www-data", domain_path], check=True)
    subprocess.run(["chmod", "-R", "755", domain_path], check=True)

    # Generate Nginx Configuration
    nginx_conf = f"""
    server {{
        listen 80;
        server_name {domain};

        root {domain_path};
        index index.php index.html index.htm;

        location / {{
            try_files $uri $uri/ /index.php?$args;
        }}

        location ~ \.php$ {{
            include snippets/fastcgi-php.conf;
            fastcgi_pass unix:{PHP_FPM_SOCK};
            fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
            include fastcgi_params;
        }}
    }}
    """

    conf_file = os.path.join(NGINX_CONFIG_PATH, domain)
    with open(conf_file, "w") as f:
        f.write(nginx_conf)

    subprocess.run(["ln", "-sf", conf_file, f"{NGINX_ENABLED_PATH}{domain}"], check=True)
    subprocess.run(["systemctl", "restart", "nginx"], check=True)

@app.post("/install/")
async def install_domain(install_data: InstallRequest):
    if not check_txt_record(install_data.domain):
        raise HTTPException(
            status_code=400,
            detail=f"Domain is not verified. Add TXT record '{VERIFICATION_TXT}' and retry."
        )

    if not check_a_record(install_data.domain):
        raise HTTPException(
            status_code=400,
            detail=f"A record not set. Please point '{install_data.domain}' to {SERVER_IP} and retry."
        )

    install_wordpress(install_data.domain)
    return {
        "message": "WordPress installation completed",
        "setup_url": f"http://{install_data.domain}/wp-admin/install.php",
        "next_step": f"Ensure A record points to {SERVER_IP}."
    }

@app.get("/is_verified/{domain}")
async def check_domain_verification(domain: str):
    """Check if domain has the required TXT record."""
    return {"verified": check_txt_record(domain)}

@app.get("/is_a_record_correct/{domain}")
async def check_domain_a_record(domain: str):
    """Check if domain A record is correctly set."""
    return {"a_record_correct": check_a_record(domain)}

@app.get("/site", response_class=HTMLResponse)
async def serve_vue_ui():
    vue_template = """<!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>WordPress Installer</title>
        <style>
            body { font-family: Arial, sans-serif; text-align: center; margin-top: 50px; }
            input, button { padding: 10px; margin: 5px; width: 300px; }
            button { background-color: blue; color: white; border: none; cursor: pointer; }
            .error { color: red; }
            .disabled { background-color: gray; cursor: not-allowed; }
        </style>
    </head>
    <body>
        <h2>Install WordPress</h2>
        <p>1️⃣ Add the following TXT record to your DNS:</p>
        <pre>wp-verify</pre>

        <input id="domain" placeholder="Enter domain (e.g. example.com)" />
        <button onclick="checkDomainVerification()">Check TXT Verification</button>
        <button onclick="checkARecord()" id="aRecordButton" disabled>Verify A Record</button>
        <button onclick="installWordPress()" id="installButton" disabled>Install WordPress</button>
        <p id="message"></p>

        <script>
            let isTxtVerified = false;
            let isARecordVerified = false;

            async function checkDomainVerification() {
                let domain = document.getElementById('domain').value;
                if (!domain) { alert("Enter a domain!"); return; }

                let response = await fetch(`/is_verified/${domain}`);
                let data = await response.json();

                if (data.verified) {
                    document.getElementById('message').innerText = "✅ TXT record verified!";
                    isTxtVerified = true;
                    document.getElementById('aRecordButton').disabled = false;
                } else {
                    document.getElementById('message').innerText = "❌ TXT record NOT verified!";
                }
            }

            async function checkARecord() {
                let domain = document.getElementById('domain').value;
                if (!domain) { alert("Enter a domain!"); return; }

                let response = await fetch(`/is_a_record_correct/${domain}`);
                let data = await response.json();

                if (data.a_record_correct) {
                    document.getElementById('message').innerText = "✅ A record correctly set!";
                    isARecordVerified = true;
                    document.getElementById('installButton').disabled = false;
                } else {
                    document.getElementById('message').innerText = "❌ A record incorrect! Set it to 172.190.115.194";
                }
            }

            async function installWordPress() {
                let domain = document.getElementById('domain').value;
                if (!domain) { alert("Enter a domain!"); return; }

                let response = await fetch('/install/', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ domain })
                });
                let data = await response.json();
                document.getElementById('message').innerText = response.ok ? "✅ WordPress Installed!" : data.detail;
            }
        </script>
    </body>
    </html>"""
    
    return HTMLResponse(content=vue_template)