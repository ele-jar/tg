# text.py

from utils import escape_markdown, format_bytes

def get_welcome_message():
    return (
        "*Welcome to the Secure Fetch Bot*\n\n"
        "I can download files from direct links or magnets and upload them to BuzzHeavier for you\.\n\n"
        "*Commands:*\n"
        "/send \- Start a new download job\.\n"
        "/info \- Get a live status of your current job\.\n"
        "/savedlinks \- View completed upload links\.\n"
        "/stats \- View all\-time data usage\.\n"
        "/h \- Check server status\.\n"
        "/cancel \- Cancel the current operation\."
    )

def get_stats_message(stats):
    total_bw = stats['downloaded'] + stats['uploaded']
    return (
        f"*\-\-\- All\-Time Statistics \-\-\-*\n"
        f"*Total Downloaded:* {escape_markdown(format_bytes(stats['downloaded']))}\n"
        f"*Total Uploaded:* {escape_markdown(format_bytes(stats['uploaded']))}\n"
        f"*Total Bandwidth Used:* {escape_markdown(format_bytes(total_bw))}"
    )

def get_server_status_message(total, used, free, total_bw):
    return (
        f"*\-\-\- Server Status \-\-\-*\n"
        f"*Disk Total:* {escape_markdown(format_bytes(total))}\n"
        f"*Disk Used:* {escape_markdown(format_bytes(used))}\n"
        f"*Disk Free:* {escape_markdown(format_bytes(free))}\n\n"
        f"*Bandwidth Used by Bot:* {escape_markdown(format_bytes(total_bw))}"
    )

def get_filename_choice_message(original, smart, short):
    return (
        f"*Choose a filename for:*\n"
        f"1\. *Full Name*: `{escape_markdown(original)}`\n"
        f"2\. *Smart Name*: `{escape_markdown(smart)}`\n"
        f"3\. *Short Name*: `{escape_markdown(short)}`\n"
        f"4\. *Custom Name*: \(You will provide this\)"
    )
