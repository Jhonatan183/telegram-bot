from telegram.ext import Updater, CommandHandler

TOKEN = "8564451538:AAH8AUwKLiEbH8B9SkVtI0wlLCu510WpU9Q"

def start(update, context):
    update.message.reply_text("🔥 BOT FUNCIONANDO")

def main():
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))

    print("BOT ENCENDIDO")
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
