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
from urllib.parse import urlparse, unquote
import mimetypes

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
        bot.send_message(chat_id, f"Welcome to the MEGA Uploader bot, {message.from_user.first_name}!\n\n"
                                  "To get started, please use the /login command to log in.")
    else:
        bot.send_message(chat_id, f"You are already registered, {message.from_user.first_name}! "
                                  "Please use the /login command to log in.")


@bot.message_handler(commands=['login'])
def login_command(message):
    chat_id = message.chat.id
    if chat_id in users:
        user = users[chat_id]
        if 'email' not in user:
            user['state'] = 'email'
            bot.send_message(chat_id, "Please enter your MEGA email.")
        else:
            bot.send_message(chat_id, "You are already logged in. Use the /upload command to upload files.")
    else:
        bot.send_message(chat_id, "You need to start the bot first with the /start command.")


@bot.message_handler(func=lambda message: True)
def handle_message(message):
    chat_id = message.chat.id
    user = users.get(chat_id)

    if user['state'] == 'email':
        # Save the email
        user['email'] = message.text.strip()
        user['state'] = 'password'
        bot.send_message(chat_id, "Email set: {}".format(user['email']))
        bot.send_message(chat_id, "Please enter your MEGA password.")
    elif user['state'] == 'password':
        # Save the password
        user['password'] = message.text.strip()
        user['state'] = 'links'
        bot.send_message(chat_id, "Password set: {}".format('*' * len(user['password'])))
        bot.send_message(chat_id, "Please enter the direct links of the files (comma-separated).")
    elif user['state'] == 'links':
        # Process the direct links and upload files
        links = message.text.strip().split(',')
        mega_instance = login_mega(user['email'], user['password'])
        if mega_instance is None:
            bot.send_message(chat_id, "MEGA login failed.")
            return

        # Create a reply keyboard markup
        reply_markup = ReplyKeyboardMarkup(resize_keyboard=True)

        # Check if a task is already in progress
        if 'current_task' in user and user['current_task'] is not None:
            # Put the new task on hold
            user['on_hold_task'] = links
            bot.send_message(chat_id, "Processing...ðŸ¤Œ\n"
                                      "The current task is in progress. The new task has been put on hold.\n"
                                      "Number of tasks on hold: {}".format(len(user['on_hold_task'])))
        else:
            # Start the new task
            user['current_task'] = links
            process_task(chat_id, mega_instance)


@bot.message_handler(commands=['cancel'])
def cancel_command(message):
    chat_id = message.chat.id
    user = users.get(chat_id)
    if user and 'current_task' in user:
        user['cancel'] = True
        if 'on_hold_task' in user:
            user['current_task'] = user['on_hold_task']
            del user['on_hold_task']
            process_task(chat_id)
        else:
            bot.send_message(chat_id, "Task cancellation requested.")


@bot.callback_query_handler(func=lambda call: call.data == "cancel_task")
def handle_callback_query(call):
    chat_id = call.message.chat.id
    user = users.get(chat_id)
    if user and 'current_task' in user:
        user['cancel'] = True
        if 'on_hold_task' in user:
            user['current_task'] = user['on_hold_task']
            del user['on_hold_task']
            process_task(chat_id)
        else:
            bot.answer_callback_query(call.id, text="Task cancellation requested.")


def login_mega(email, password):
    try:
        mega = Mega()
        m = mega.login(email, password)
        print("Login successful!")
        return m
    except Exception as e:
        print("Login failed:", str(e))
        return None


def upload_file(mega, file_path, file_name):
    try:
        # Decode the file name if it's Base64 encoded
        if "?" in file_name:
            file_name = file_name.split("?")[0]
            file_name = base64.urlsafe_b64decode(file_name).decode()

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
                        f"[{'â—‹' * (10 - (percent // 10))}{'â—' * (percent // 10)}]\n" \
                        f"{format_size(progress_bar.format_dict['n'])} of {total_size_formatted}\n" \
                        f"Speed: {speed_formatted}\n" \
                        f"ETA: {remaining}"
    else:
        progress_text = f"Downloading file:\n\n" \
                        f"[{'â—‹' * (10 - (percent // 10))}{'â—' * (percent // 10)}]\n" \
                        f"{format_size(progress_bar.format_dict['n'])} of {total_size_formatted}\n" \
                        f"Speed: {speed_formatted}"

    cancel_button = InlineKeyboardButton("Cancel Task", callback_data="cancel_task")
    inline_keyboard = InlineKeyboardMarkup().add(cancel_button)
    bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=progress_text,
                          reply_markup=inline_keyboard)


def format_size(size):
    units = ["B", "KB", "MB", "GB", "TB"]
    index = 0
    while size >= 1024 and index < len(units) - 1:
        size /= 1024
        index += 1
    size_formatted = "{:.2f} {}".format(size, units[index])
    return size_formatted


def process_task(chat_id, mega_instance):
    user = users.get(chat_id)
    if not user:
        return

    links = user['current_task']

    # Upload the files
    for link in links:
        link = link.strip()

        # Download the file from the direct link
        response = requests.get(link, stream=True)
        file_name = link.split('/')[-1]
        file_size = response.headers.get('Content-Length')

        # Check if the file is too large to upload
        max_file_size = 10000 * 1024 * 1024  # Set maximum file size to 10000 MB
        if file_size is not None and int(file_size) > max_file_size:
            bot.send_message(chat_id, "File is too large to upload: {}".format(file_name))
            continue

        # Download the file and display progress
        temp_file_path = os.path.join(tempfile.gettempdir(), file_name)
        with open(temp_file_path, 'wb') as file:
            total_size = int(file_size) if file_size is not None else 0
            chunk_size = 1024 * 1024  # 1 MB chunk size
            progress_bar = tqdm(total=total_size, unit='B', unit_scale=True, ncols=50,
                                bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}]')

            progress_message = bot.send_message(chat_id, f"Downloading file:\n\n"
                                                         f"[{'â–«' * 10}]\n"
                                                         f"0B of {format_size(total_size)}",
                                                reply_markup=InlineKeyboardMarkup().add(
                                                    InlineKeyboardButton("Cancel Task", callback_data="cancel_task")))

            start_time = time.time()
            for chunk in response.iter_content(chunk_size):
                if 'cancel' in user and user['cancel']:
                    # Remove the cancel flag and stop the task
                    user['cancel'] = False
                    progress_bar.close()
                    bot.edit_message_text(chat_id=chat_id, message_id=progress_message.message_id,
                                          text="Task canceled.")
                    return

                file.write(chunk)
                progress_bar.update(len(chunk))
                current_time = time.time()
                elapsed_time = current_time - start_time

                # Update progress every 5 seconds
                if elapsed_time > 5:
                    update_progress(chat_id, progress_message.message_id, progress_bar, total_size)
                    start_time = current_time

            progress_bar.close()

        # Check the file type
        file_type = get_file_type(temp_file_path)

        if file_type == 'video':
            # Upload the video file to MEGA
            uploaded_file = upload_file(mega_instance, temp_file_path, file_name)

            if uploaded_file is not None:
                # Get the download link of the uploaded file
                download_url = mega_instance.get_upload_link(uploaded_file)
                short_name = get_short_name(file_name)
                bot.send_message(chat_id, "Video file uploaded to MEGA: {}\n\n"
                                          "Download link: {}".format(short_name, download_url))
            else:
                bot.send_message(chat_id, "Failed to upload video file to MEGA: {}".format(file_name))

        elif file_type == 'application':
            # Check if the file already exists in MEGA
            if mega_instance.find(temp_file_path):
                bot.send_message(chat_id, "File already exists in MEGA: {}".format(file_name))
                os.remove(temp_file_path)
                continue

            # Upload the application file to MEGA
            uploaded_file = upload_file(mega_instance, temp_file_path, file_name)

            if uploaded_file is not None:
                # Get the download link of the uploaded file
                download_url = mega_instance.get_upload_link(uploaded_file)
                short_name = get_short_name(file_name)
                bot.send_message(chat_id, "Application file uploaded to MEGA: {}\n\n"
                                          "Download link: {}".format(short_name, download_url))
            else:
                bot.send_message(chat_id, "Failed to upload application file to MEGA: {}".format(file_name))

        else:
            bot.send_message(chat_id, "Unsupported file type: {}".format(file_name))

        # Remove the temporary file
        os.remove(temp_file_path)

    # Remove the current task from the user data
    del user['current_task']

    # Check if there is an on-hold task
    if 'on_hold_task' in user:
        on_hold_task = user['on_hold_task']
        del user['on_hold_task']
        user['current_task'] = on_hold_task
        process_task(chat_id, mega_instance)
    else:
        bot.send_message(chat_id, "Task completed.")



def get_file_type(file_path):
    mime_type, _ = mimetypes.guess_type(file_path)
    if mime_type is None:
        return None

    if mime_type.startswith('video'):
        return 'video'
    elif mime_type.startswith('application'):
        return 'application'

    return None


def get_short_name(file_name):
    if len(file_name) > 30:
        short_name = file_name[:20] + "..." + file_name[-7:]
    else:
        short_name = file_name
    return short_name


bot.polling()
