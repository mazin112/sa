import requests
from mega import Mega
from telebot import TeleBot
from telebot.types import ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton
import tempfile
import os
from tqdm import tqdm
import math
import time
import base64

# Telegram bot token
TOKEN = '6235045070:AAF_tTnNTDYBrNQhO7rkBuDpF6fcl21Ilss'

# Initialize the Telebot instance
bot = TeleBot(TOKEN)

# Dictionary to store user data
users = {}


@bot.message_handler(commands=['start'])
def start_command(message):
    chat_id = message.chat.id
    if chat_id not in users:
        users[chat_id] = {'state': 'email'}
        bot.reply_to(message, f"Welcome to the MEGA Uploader bot, {message.from_user.first_name}!\n\n"
                              "To get started, please use the /login command to log in.")
    else:
        bot.reply_to(message, f"You are already registered, {message.from_user.first_name}! "
                              "Please use the /login command to log in.")


@bot.message_handler(commands=['login'])
def login_command(message):
    chat_id = message.chat.id
    if chat_id in users:
        user = users[chat_id]
        if 'email' not in user:
            user['state'] = 'email'
            bot.reply_to(message, "Please enter your MEGA email.")
        else:
            bot.reply_to(message, "You are already logged in. Use the /upload command to upload files.")
    else:
        bot.reply_to(message, "You need to start the bot first with the /start command.")


@bot.message_handler(func=lambda message: True)
def handle_message(message):
    chat_id = message.chat.id
    user = users.get(chat_id)

    if user['state'] == 'email':
        # Save the email
        user['email'] = message.text.strip()
        user['state'] = 'password'
        bot.reply_to(message, "Email set: {}".format(user['email']))
        bot.reply_to(message, "Please enter your MEGA password.")
    elif user['state'] == 'password':
        # Save the password
        user['password'] = message.text.strip()
        user['state'] = 'links'
        bot.reply_to(message, "Password set: {}".format('*' * len(user['password'])))
        bot.reply_to(message, "Please enter the direct links of the files (comma-separated).")
    elif user['state'] == 'links':
        # Process the direct links and upload files
        links = message.text.strip().split(',')
        mega_instance = login_mega(user['email'], user['password'])
        if mega_instance is None:
            bot.reply_to(message, "MEGA login failed.")
        else:
            upload_files(chat_id, mega_instance, links, message)  # Pass the 'message' parameter


def login_mega(email, password):
    try:
        mega = Mega()
        m = mega.login(email, password)
        print("Login successful!")
        return m
    except Exception as e:
        print("Login failed:", str(e))
        return None


def upload_files(chat_id, mega, links, message):  # Add 'message' parameter
    for link in links:
        link = link.strip()

        # Download the file from the direct link
        response = requests.get(link, stream=True)
        file_name = link.split('/')[-1]
        file_size = response.headers.get('Content-Length')

        # Download the file and display progress
        temp_file_path = os.path.join(tempfile.gettempdir(), file_name)
        total_size = int(file_size)
        chunk_size = 1024 * 1024  # 1 MB chunk size

        progress_message = bot.reply_to(message, "Downloading file: {}".format(file_name))

        with tqdm(total=total_size, unit='B', unit_scale=True, unit_divisor=1024) as progress_bar:
            start_time = time.time()

            with open(temp_file_path, 'wb') as file:
                for chunk in response.iter_content(chunk_size=chunk_size):
                    if chunk:
                        file.write(chunk)
                        progress_bar.update(len(chunk))
                        current_time = time.time()
                        elapsed_time = current_time - start_time

                        # Update progress every 5 seconds
                        if elapsed_time > 5:
                            update_progress(chat_id, progress_message.message_id, progress_bar, total_size)
                            start_time = current_time

            progress_bar.close()

        # Remove the progress message for download
        bot.delete_message(chat_id, progress_message.message_id)

        # Save upload progress info
        if 'upload_info' not in users[chat_id]:
            users[chat_id]['upload_info'] = {}
        users[chat_id]['upload_info'][file_name] = {'total_size': total_size, 'progress_bar': progress_bar}

        # Send progress message for upload
        upload_progress_message = bot.reply_to(message, "Uploading file to MEGA: {}".format(file_name))

        # Upload the file to MEGA
        uploaded_file = upload_file(mega, temp_file_path, file_name)

        if uploaded_file is not None:
            # Get the download link of the uploaded file
            download_url = mega.get_upload_link(uploaded_file)
            bot.reply_to(message, "File uploaded to MEGA: {}\n\n"
                                  "Download link: {}".format(file_name, download_url))
        else:
            bot.reply_to(message, "Failed to upload file to MEGA: {}".format(file_name))

        # Remove the temporary file
        os.remove(temp_file_path)

        # Remove the progress message for upload
        bot.delete_message(chat_id, upload_progress_message.message_id)


def upload_file(mega, file_path, file_name):
    try:
        uploaded_file = mega.find(file_name)
        if uploaded_file:
            print("File already exists in MEGA:", file_name)
            return uploaded_file[0]
        else:
            file = mega.upload(file_path)
            print("File upload complete!")
            return file
    except Exception as e:
        print("File upload failed:", str(e))
        return None


def update_progress(chat_id, message_id, progress_bar, total_size):
    percent = math.floor(progress_bar.n / total_size * 100)
    speed = progress_bar.format_dict["rate"]
    elapsed = progress_bar.format_dict["elapsed"]

    # Convert file size to human-readable format
    total_size_formatted = format_size(total_size)

    # Convert download speed to human-readable format
    speed_formatted = format_size(speed) + '/s'

    if "remaining" in progress_bar.format_dict:
        remaining = progress_bar.format_dict["remaining"]
        progress_text = f"Downloading file:\n\n" \
                        f"[{'○' * (10 - (percent // 10))}{'●' * (percent // 10)}]\n" \
                        f"{format_size(progress_bar.format_dict['n'])} of {total_size_formatted}\n" \
                        f"Speed: {speed_formatted}\n" \
                        f"ETA: {remaining}"
    else:
        progress_text = f"Downloading file:\n\n" \
                        f"[{'○' * (10 - (percent // 10))}{'●' * (percent // 10)}]\n" \
                        f"{format_size(progress_bar.format_dict['n'])} of {total_size_formatted}\n" \
                        f"Speed: {speed_formatted}"

    # Update the progress message with a fancy progress bar
    progress_text += f"\n\nProgress: {'█' * (percent // 10)}{' ' * ((100 - percent) // 10)} {percent}%"

    bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=progress_text)


def format_size(size):
    power = 2 ** 10
    n = 0
    power_labels = {0: '', 1: 'K', 2: 'M', 3: 'G', 4: 'T'}
    while size > power:
        size /= power
        n += 1
    return str(round(size, 2)) + ' ' + power_labels[n] + 'B'


bot.polling()
