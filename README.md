# nlp_api
main.py - main file to run API. Need to change the name of the file for the corresponding API

app_male_words_de_sm_false.py - Main API to analyse the user query icluding rules and NLP to avoid False Positives

app_ld.py - API to recognise the language of the user query

app_male_words_de.py - API to check if the user query have the Male Coded Terms in German. Output: caught word, start, lenght of the word, category, alternatives

app_pos_er_de.py - API for part-of-the-speach analisys and the named entities recognition extract, German. Output is the list with extracted items

app_pos_er_en.py - API for part-of-the-speach analisys and the named entities recognition extract, English. Output is the list with extracted items

app_er_de.py - API for the named entities recognition extraction, German. Output: extracted word, start and the end of the word in the sentence, label 

app_er_en.py - API for the named entities recognition extraction, English. Output: extracted word, start and the end of the word in the sentence, label 
