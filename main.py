#entry point
#import server
import uvicorn


# want to server to run app.py in the folder app as main app, port=8000 is defaut port for the fast api
# reload=True is debag mode in Flask is on, to set =False, when deploy the app to the production
# might be added host="0.0.0.0"
if __name__=="__main__":
	uvicorn.run("app.app_male_words_de:app", port=8000, reload=True)