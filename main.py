from fastapi import FastAPI, Request, HTTPException, Response
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel
import subprocess
import os
import asyncio
from typing import AsyncGenerator
import logging
import sys

# Set up logging with immediate flushing
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("install.log"),
        logging.StreamHandler(sys.stdout)
    ],
    force=True
)
logger = logging.getLogger(__name__)
logger.handlers[0].stream.flush = sys.stdout.flush  # Ensure immediate output

app = FastAPI()

# Configurable Paths
WORDPRESS_DIR = os.getenv("WORDPRESS_DIR", "/var/www/")
NGINX_CONFIG_PATH = os.getenv("NGINX_CONFIG_PATH", "/etc/nginx/sites-available/")
NGINX_ENABLED_PATH = os.getenv("NGINX_ENABLED_PATH", "/etc/nginx/sites-enabled/")
PHP_FPM_SOCK = os.getenv("PHP_FPM_SOCK", "/run/php/php7.4-fpm.sock")

VERIFICATION_TXT = "wp-verify"
SERVER_IP = "172.190.115.194"

class InstallRequest(BaseModel):
    domain: str

def check_txt_record(domain: str) -> bool:
    try:
        result = subprocess.run(["dig", "+short", "TXT", domain], capture_output=True, text=True)
        logger.info(f"TXT check for {domain}: {result.stdout}")
        return VERIFICATION_TXT in result.stdout
    except Exception as e:
        logger.error(f"Error checking TXT record for {domain}: {e}")
        return False

def check_a_record(domain: str) -> bool:
    try:
        result = subprocess.run(["dig", "+short", domain], capture_output=True, text=True)
        logger.info(f"A record check for {domain}: {result.stdout}")
        return SERVER_IP in result.stdout.strip().split("\n")
    except Exception as e:
        logger.error(f"Error checking A record for {domain}: {e}")
        return False

async def install_wordpress_stream(domain: str) -> AsyncGenerator[str, None]:
    domain_path = os.path.join(WORDPRESS_DIR, domain)
    logger.info(f"Starting installation for {domain} at {domain_path}")

    if os.path.exists(domain_path):
        yield "data: Domain already installed.\n\n"
        return

    if not check_txt_record(domain):
        yield f"data: Domain is not verified. Add TXT record '{VERIFICATION_TXT}' and retry.\n\n"
        return

    if not check_a_record(domain):
        yield f"data: A record not set. Please point '{domain}' to {SERVER_IP} and retry.\n\n"
        return

    try:
        # Check directory permissions before creating
        parent_dir = os.path.dirname(domain_path)
        if not os.access(parent_dir, os.W_OK):
            yield f"data: ❌ Cannot write to {parent_dir}. Check permissions.\n\n"
            logger.error(f"Cannot write to {parent_dir}")
            return

        yield "data: Creating directory...\n\n"
        logger.info("Attempting to create directory")
        result = subprocess.run(["sudo", "mkdir", "-p", domain_path], check=True, capture_output=True, text=True)
        logger.info(f"Directory created: {result.stdout}")

        yield "data: Downloading WordPress...\n\n"
        logger.info("Starting WordPress download")
        result = subprocess.run(["sudo", "wget", "https://wordpress.org/latest.tar.gz", "-P", domain_path], check=True, capture_output=True, text=True)
        logger.info(f"Download completed: {result.stdout}")

        yield "data: Extracting files...\n\n"
        logger.info("Extracting files")
        result = subprocess.run(["sudo", "tar", "-xzf", f"{domain_path}/latest.tar.gz", "-C", domain_path, "--strip-components=1"], check=True, capture_output=True, text=True)
        logger.info(f"Extraction completed: {result.stdout}")
        subprocess.run(["sudo", "rm", f"{domain_path}/latest.tar.gz"], check=True, capture_output=True, text=True)
        logger.info("Temporary tar file removed")

        yield "data: Configuring permissions...\n\n"
        logger.info("Configuring permissions")
        subprocess.run(["sudo", "chown", "-R", "www-data:www-data", domain_path], check=True, capture_output=True, text=True)
        subprocess.run(["sudo", "chmod", "-R", "755", domain_path], check=True, capture_output=True, text=True)
        logger.info("Permissions configured")

        yield "data: Setting up Nginx...\n\n"
        logger.info("Setting up Nginx")
        nginx_conf = f"""
        server {{
            listen 80;
            server_name {domain};

            root {domain_path};
            index index.php index.html index.htm;

            location / {{
                try_files $uri $uri/ /index.php?$args;
            }}

            location ~ \.php$ %%
                include snippets/fastcgi-php.conf;
                fastcgi_pass unix:{PHP_FPM_SOCK};
                fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
                include fastcgi_params;
            }}
        }}
        """
        conf_file = os.path.join(NGINX_CONFIG_PATH, domain)
        with open("temp_nginx_conf", "w") as f:
            f.write(nginx_conf)
        subprocess.run(["sudo", "mv", "temp_nginx_conf", conf_file], check=True, capture_output=True, text=True)
        subprocess.run(["sudo", "ln", "-sf", conf_file, f"{NGINX_ENABLED_PATH}/{domain}"], check=True, capture_output=True, text=True)
        subprocess.run(["sudo", "systemctl", "restart", "nginx"], check=True, capture_output=True, text=True)
        logger.info("Nginx configured and restarted")

        yield f"data: ✅ WordPress installed! Visit: http://{domain}/wp-admin/install.php\n\n"
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr or str(e)
        logger.error(f"Subprocess error: {error_msg}")
        yield f"data: ❌ Installation failed: {error_msg}\n\n"
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        yield f"data: ❌ Unexpected error during installation: {str(e)}\n\n"
    finally:
        logger.info(f"Installation stream for {domain} ended")

@app.get("/install/{domain}")
async def install_domain_stream(domain: str):
    return StreamingResponse(install_wordpress_stream(domain), media_type="text/event-stream")

@app.get("/is_verified/{domain}")
async def check_domain_verification(domain: str):
    return {"verified": check_txt_record(domain)}

@app.get("/is_a_record_correct/{domain}")
async def check_domain_a_record(domain: str):
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
            body { 
                font-family: Arial, sans-serif; 
                text-align: center; 
                margin-top: 50px; 
            }
            .container {
                display: flex;
                flex-direction: column;
                align-items: center;
                gap: 10px;
            }
            input, button { 
                padding: 10px; 
                width: 300px; 
                box-sizing: border-box;
            }
            button { 
                background-color: blue; 
                color: white; 
                border: none; 
                cursor: pointer; 
            }
            button:disabled { 
                background-color: gray; 
                cursor: not-allowed; 
            }
            .hidden { display: none; }
            .progress { 
                margin-top: 10px; 
                font-style: italic; 
            }
            .error { color: red; }
        </style>
    </head>
    <body>
        <h2>Install WordPress</h2>
        <p>1️⃣ Add the following TXT record to your DNS:</p>
        <pre>wp-verify</pre>

        <div class="container">
            <input id="domain" placeholder="Enter domain (e.g. example.com)" />
            <button id="txtButton" onclick="checkDomainVerification()">Check TXT Verification</button>
            <button id="aRecordButton" class="hidden" onclick="checkARecord()">Verify A Record</button>
            <button id="installButton" class="hidden" onclick="installWordPress()">Install WordPress</button>
            <p id="message"></p>
            <p id="progress" class="progress hidden"></p>
        </div>

        <script>
            const messageEl = document.getElementById('message');
            const progressEl = document.getElementById('progress');
            const txtButton = document.getElementById('txtButton');
            const aRecordButton = document.getElementById('aRecordButton');
            const installButton = document.getElementById('installButton');

            async function checkDomainVerification() {
                let domain = document.getElementById('domain').value;
                if (!domain) { alert("Enter a domain!"); return; }

                txtButton.disabled = true;
                messageEl.innerText = "Checking TXT record...";
                
                let response = await fetch(`/is_verified/${domain}`);
                let data = await response.json();

                txtButton.disabled = false;
                if (data.verified) {
                    messageEl.innerText = "✅ TXT record verified!";
                    aRecordButton.classList.remove('hidden');
                } else {
                    messageEl.innerText = "❌ TXT record NOT verified!";
                }
            }

            async function checkARecord() {
                let domain = document.getElementById('domain').value;
                if (!domain) { alert("Enter a domain!"); return; }

                aRecordButton.disabled = true;
                messageEl.innerText = "Checking A record...";
                
                let response = await fetch(`/is_a_record_correct/${domain}`);
                let data = await response.json();

                aRecordButton.disabled = false;
                if (data.a_record_correct) {
                    messageEl.innerText = "✅ A record correctly set!";
                    installButton.classList.remove('hidden');
                } else {
                    messageEl.innerText = "❌ A record incorrect! Set it to 172.190.115.194";
                }
            }

            function installWordPress() {
                let domain = document.getElementById('domain').value;
                if (!domain) { alert("Enter a domain!"); return; }

                installButton.disabled = true;
                messageEl.innerText = "Starting WordPress installation...";
                progressEl.classList.remove('hidden');
                progressEl.innerText = "Initializing...";

                const eventSource = new EventSource(`/install/${domain}`);
                eventSource.onmessage = (event) => {
                    progressEl.innerText = event.data;
                    console.log("SSE Message:", event.data);
                    if (event.data.includes("✅ WordPress installed!")) {
                        eventSource.close();
                        installButton.disabled = false;
                        messageEl.innerText = event.data;
                        progressEl.classList.add('hidden');
                    } else if (event.data.includes("❌")) {
                        eventSource.close();
                        installButton.disabled = false;
                        messageEl.innerText = event.data;
                        messageEl.classList.add('error');
                        progressEl.classList.add('hidden');
                    }
                };
                eventSource.onerror = (error) => {
                    console.error("SSE Error:", error);
                    progressEl.innerText = "Connection lost. Check server logs for details.";
                    messageEl.innerText = "❌ Installation interrupted.";
                    messageEl.classList.add('error');
                    eventSource.close();
                    installButton.disabled = false;
                };
                eventSource.onopen = () => {
                    console.log("SSE connection opened");
                };
            }
        </script>
    </body>
    </html>"""
    
    return HTMLResponse(content=vue_template)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)