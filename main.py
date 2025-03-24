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

# Allowed Referrers
ALLOWED_REFERRERS = ["globalform.us", "globaltrade.us"]

# Mock function to check if a domain is verified
def is_domain_verified(domain: str) -> bool:
    # TODO: Replace with actual verification check (e.g., database lookup)
    verified_domains = ["example.com", "verifiedsite.com"]
    return domain in verified_domains

class InstallRequest(BaseModel):
    domain: str

def run_command(command):
    """Execute shell command securely and handle errors."""
    try:
        subprocess.run(command, check=True, shell=True)
    except subprocess.CalledProcessError as e:
        print(f"Error executing command: {command}\n{e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")

def install_wordpress(domain: str):
    """Installs WordPress for a given domain."""
    domain_path = os.path.join(WORDPRESS_DIR, domain)
    
    if os.path.exists(domain_path):
        print(f"⚠️ Domain {domain} already installed.")
        return
    
    if not is_domain_verified(domain):
        raise HTTPException(status_code=400, detail="Domain is not verified.")

    # Create directory and download WordPress
    run_command(f"sudo mkdir -p {domain_path}")
    run_command(f"wget https://wordpress.org/latest.tar.gz -P {domain_path}")
    run_command(f"tar -xzf {domain_path}/latest.tar.gz -C {domain_path} --strip-components=1")
    run_command(f"rm {domain_path}/latest.tar.gz")

    # Set correct permissions
    run_command(f"sudo chown -R www-data:www-data {domain_path}")
    run_command(f"sudo chmod -R 755 {domain_path}")

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
    
    run_command(f"sudo ln -sf {conf_file} {NGINX_ENABLED_PATH}{domain}")
    run_command("sudo systemctl restart nginx")
    
    print(f"✅ WordPress installed at {domain}")

@app.post("/install/")
async def install_domain(request: Request, install_data: InstallRequest):
    if not is_domain_verified(install_data.domain):
        raise HTTPException(status_code=400, detail="Domain is not verified. Please verify your domain first.")
    
    install_wordpress(install_data.domain)
    return {"message": "WordPress Installation completed", "setup_url": f"http://{install_data.domain}/wp-admin/install.php"}

@app.get("/is_verified/{domain}")
async def check_domain_verification(domain: str):
    """API Endpoint to check if a domain is verified."""
    return {"verified": is_domain_verified(domain)}

@app.get("/site", response_class=HTMLResponse)
async def serve_vue_ui(request: Request):
    vue_template = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>WordPress Installer</title>
        <style>
            body { font-family: Arial, sans-serif; text-align: center; margin-top: 50px; }
            input { padding: 10px; width: 300px; margin-bottom: 10px; }
            button { padding: 10px; background-color: blue; color: white; border: none; cursor: pointer; margin: 5px; }
            .error { color: red; }
            .disabled { background-color: gray; cursor: not-allowed; }
        </style>
    </head>
    <body>
        <h2>Install WordPress</h2>
        <input id="domain" placeholder="Enter domain (e.g. example.com)" />
        <button onclick="checkDomainVerification()">Check Verification</button>
        <button onclick="installWordPress()" id="installButton" disabled>Install WordPress</button>
        <p id="message"></p>

        <script>
            async function checkDomainVerification() {
                const domain = document.getElementById('domain').value;
                if (!domain) {
                    document.getElementById('message').innerText = "Enter a domain!";
                    return;
                }

                let response = await fetch(`/is_verified/${domain}`);
                let data = await response.json();

                if (data.verified) {
                    document.getElementById('message').innerText = "✅ Domain is verified!";
                    document.getElementById('installButton').disabled = false;
                    document.getElementById('installButton').classList.remove("disabled");
                } else {
                    document.getElementById('message').innerText = "❌ Domain is NOT verified!";
                    document.getElementById('installButton').disabled = true;
                    document.getElementById('installButton').classList.add("disabled");
                }
            }

            async function installWordPress() {
                const domain = document.getElementById('domain').value;
                if (!domain) {
                    document.getElementById('message').innerText = "Enter a domain!";
                    return;
                }
                
                try {
                    let response = await fetch('/install/', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ domain })
                    });
                    let data = await response.json();
                    
                    if (response.ok) {
                        document.getElementById('message').innerHTML = "✅ WordPress Installed! <a href='" + data.setup_url + "' target='_blank'>Setup Here</a>";
                    } else {
                        document.getElementById('message').innerText = data.detail || "Error installing WordPress";
                    }
                } catch (error) {
                    document.getElementById('message').innerText = "Error installing WordPress";
                }
            }
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=vue_template)
