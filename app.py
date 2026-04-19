from flask import Flask, request, jsonify
import asyncio
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
from google.protobuf.json_format import MessageToJson
import binascii
import aiohttp
import requests
import json
import like_pb2
import like_count_pb2
import uid_generator_pb2
from google.protobuf.message import DecodeError

app = Flask(__name__)

def load_tokens(server_name):
    try:
        # Case 1: PK or BD servers load from token_pk.json
        if server_name in {"PK", "BD"}:
            with open("token_pk.json", "r") as f:
                tokens = json.load(f)
        
        # Case 2: IND server loads specifically from token_ind.json
        elif server_name == "IND":
            with open("token_pk.json", "r") as f:
                tokens = json.load(f)
        
        # Case 3: Other regions - Combine tokens from PK and IND files
        else:
            tokens = []
            try:
                with open("token_pk.json", "r") as f:
                    tokens.extend(json.load(f))
            except FileNotFoundError:
                app.logger.warning("token_pk.json not found")
            
            try:
                with open("token_ind.json", "r") as f:
                    tokens.extend(json.load(f))
            except FileNotFoundError:
                app.logger.warning("token_ind.json not found")
                
        return tokens
    except Exception as e:
        app.logger.error(f"Error loading tokens for server {server_name}: {e}")
        return None

def encrypt_message(plaintext):
    try:
        key = b'Yg&tc%DEuh6%Zc^8'
        iv = b'6oyZDr22E3ychjM%'
        cipher = AES.new(key, AES.MODE_CBC, iv)
        padded_message = pad(plaintext, AES.block_size)
        encrypted_message = cipher.encrypt(padded_message)
        return binascii.hexlify(encrypted_message).decode('utf-8')
    except Exception:
        return None

def create_protobuf_message(user_id, region):
    try:
        message = like_pb2.like()
        message.uid = int(user_id)
        message.region = region
        return message.SerializeToString()
    except Exception:
        return None

async def send_request(encrypted_uid, token, url):
    try:
        edata = bytes.fromhex(encrypted_uid)
        headers = {
            'User-Agent': "Dalvik/2.1.0 (Linux; U; Android 9; ASUS_Z01QD Build/PI)",
            'Authorization': f"Bearer {token}",
            'Content-Type': "application/x-www-form-urlencoded",
            'X-Unity-Version': "2018.4.11f1",
            'ReleaseVersion': "OB53"
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=edata, headers=headers) as response:
                return response.status
    except Exception:
        return None

async def send_multiple_requests(uid, server_name, url):
    try:
        protobuf_message = create_protobuf_message(uid, server_name)
        encrypted_uid = encrypt_message(protobuf_message)
        tokens = load_tokens(server_name)
        if not tokens or not encrypted_uid:
            return None
        tasks = []
        for i in range(100):
            token = tokens[i % len(tokens)]["token"]
            tasks.append(send_request(encrypted_uid, token, url))
        return await asyncio.gather(*tasks, return_exceptions=True)
    except Exception:
        return None

def create_protobuf(uid):
    try:
        message = uid_generator_pb2.uid_generator()
        message.saturn_ = int(uid)
        message.garena = 1
        return message.SerializeToString()
    except Exception:
        return None

def enc(uid):
    data = create_protobuf(uid)
    return encrypt_message(data) if data else None

def make_request(encrypt, server_name, token):
    try:
        # URL selection logic based on requested server
        if server_name in {"PK", "BD"}:
            url = "https://clientbp.ggblueshark.com/GetPlayerPersonalShow"
        elif server_name == "IND":
            url = "https://client.ind.freefiremobile.com/GetPlayerPersonalShow"
        else:
            url = "https://client.us.freefiremobile.com/GetPlayerPersonalShow"
            
        edata = bytes.fromhex(encrypt)
        headers = {
            'User-Agent': "Dalvik/2.1.0 (Linux; U; Android 9; ASUS_Z01QD Build/PI)",
            'Authorization': f"Bearer {token}",
            'Content-Type': "application/x-www-form-urlencoded",
            'X-Unity-Version': "2018.4.11f1",
            'ReleaseVersion': "OB53"
        }
        response = requests.post(url, data=edata, headers=headers, verify=False, timeout=10)
        items = like_count_pb2.Info()
        items.ParseFromString(response.content)
        return items
    except Exception:
        return None

def fetch_player_info(uid):
    try:
        url = f"https://nr-codex-info.vercel.app/get?uid={uid}"
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            data = response.json()
            acc = data.get("AccountInfo", {})
            return {"Level": acc.get("AccountLevel", "NA"), "Region": acc.get("AccountRegion", "NA")}
    except Exception:
        pass
    return {"Level": "NA", "Region": "NA"}

@app.route('/like', methods=['GET'])
def handle_requests():
    uid = request.args.get("uid")
    server_name = request.args.get("server_name", "").upper()
    if not uid or not server_name:
        return jsonify({"error": "Missing UID or server_name"}), 400

    try:
        # Use strictly the server_name provided by user
        server_name_used = server_name

        tokens = load_tokens(server_name_used)
        if not tokens: 
            return jsonify({"error": f"No tokens available for {server_name_used}"}), 500
        
        token = tokens[0]['token']
        encrypted_uid = enc(uid)
        if not encrypted_uid: 
            return jsonify({"error": "Encryption failed"}), 500

        # Initial profile check with safety verification
        before = make_request(encrypted_uid, server_name_used, token)
        if before is None:
            return jsonify({"error": "Failed to fetch initial profile data. Check your tokens."}), 500

        data_before = json.loads(MessageToJson(before))
        before_like = int(data_before.get('AccountInfo', {}).get('Likes', 0))

        # Determine target API for liking
        if server_name_used in {"PK", "BD"}:
            like_url = "https://clientbp.ggblueshark.com/LikeProfile"
        elif server_name_used == "IND":
            like_url = "https://client.ind.freefiremobile.com/LikeProfile"
        else:
            like_url = "https://client.us.freefiremobile.com/LikeProfile"

        # Fire asynchronous like requests
        asyncio.run(send_multiple_requests(uid, server_name_used, like_url))

        # Final profile check with safety verification
        after = make_request(encrypted_uid, server_name_used, token)
        if after is None:
            return jsonify({"error": "Could not verify final likes. Action may have completed."}), 500

        data_after = json.loads(MessageToJson(after))
        after_like = int(data_after.get('AccountInfo', {}).get('Likes', 0))
        
        # Determine player region for response info
        player_info = fetch_player_info(uid)
        
        return jsonify({
            "LikesGivenByAPI": after_like - before_like,
            "LikesafterCommand": after_like,
            "LikesbeforeCommand": before_like,
            "PlayerNickname": data_after.get('AccountInfo', {}).get('PlayerNickname', ''),
            "Region": player_info["Region"],
            "Level": player_info["Level"],
            "UID": uid,
            "status": 1 if (after_like - before_like) != 0 else 2
        })
    except Exception as e:
        app.logger.error(f"Error: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, use_reloader=False)
