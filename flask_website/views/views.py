from flask_website import app

from flask import render_template, request, redirect, session, url_for, flash

#Using the following tibber wrapper: https://github.com/BeatsuDev/tibber.py
import tibber

import datetime

from datetime import timezone

import pytz

import math

import pandas as pd

from flask_website.config import get_db_connection, tibber_token
from flask_website.db import get_all_starttimes, get_all_stoptimes,  get_all_starttimes_cons, get_all_starttimes_cost

@app.route("/")
def index():

    return render_template("index.html")

@app.route("/viewaday", methods=["GET", "POST"])
def viewaday():

    if request.method == "GET":

        date_time = datetime.datetime.now()
        date = date_time.strftime("%Y-%m-%d")

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM collecteddata WHERE date = (%s) ORDER BY start DESC",
                    (date,))
        datatoday = cur.fetchall()
        cur.close()
        conn.close()

    if request.method == "POST":

        req = request.form
        date = req["date"]

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM collecteddata WHERE date = (%s) ORDER BY start DESC",
                    (date,))
        datatoday = cur.fetchall()
        cur.close()
        conn.close()

    return render_template("viewaday.html", datatoday=datatoday, date=date)

@app.route("/setup", methods=["GET", "POST"])
def setup():

    if request.method == "POST":

        req = request.form 

        fixedmontlycost = req["fixedmontlycost"]
        fixedkwhcost    = req["fixedkwhcost"]

        session["fixedmontlycost"] = fixedmontlycost
        session["fixedkwhcost"] =   fixedkwhcost      

        #Flasher beskjeder dersom input data er lagret
        if fixedmontlycost != '' and fixedkwhcost != '':
            flash("Figures are successfully saved for this session")
            return redirect("/setup")
    
    return render_template("/setup.html")

@app.route("/collectdata", methods=["GET", "POST"])
def collectdata():

    return render_template("/collectdata.html")

@app.route("/datacollected", methods=["GET", "POST"])
def datacollected():

    if request.method == "POST":

        req = request.form 
        action = req.get("action")
        hourstocollect = req["hourstocollect"]

        if action[13:16] == "24 ":
            hourstocollect = 24
        
        if action[13:16] == "48 ":
            hourstocollect = 48

        if action[13:16] == "72 ":
            hourstocollect = 72

        if action[13:16] == "168":
            hourstocollect = 168

        if action[13:16] == "inp" and hourstocollect != "":
            hourstocollect = int(hourstocollect)

        if action[13:16] == "inp" and hourstocollect == "":
            flash("Please input a number before clicking collect data")
            return redirect("/collectdata")

        if action[13:16] == "whe":

            #Getting all stop times collected and make them into a list
            stoptimes_tup=get_all_stoptimes()
            stoptimes  = [tupleObj[0] for tupleObj in stoptimes_tup]

            #Sorting the list descending
            stoptimes.sort(reverse=True, key=lambda date: datetime.datetime.strptime(date, '%Y-%m-%dT%H:%M'))

            #Keeping the first item in the list, i.e. the newest stop time
            lastcollected = stoptimes[0]

            #Converting stop time into a datetime object and making it timezone (ECT) aware
            lastcollected2=datetime.datetime.strptime(lastcollected, '%Y-%m-%dT%H:%M')
            ect_timezone = pytz.timezone('Europe/Berlin')            
            lastcollected2 = lastcollected2.astimezone(ect_timezone)

            #Local date and time converted to European Central Time since the app can run in any timezone
            date_time_now = datetime.datetime.now()
            date_time = date_time_now.astimezone(ect_timezone)

            #Calculating how many hours has passed since last data collection
            tdelta = date_time - lastcollected2
            tsecs = tdelta.total_seconds()
            thours = math.floor(tsecs/(3600))

            hourstocollect = int(thours)

        if hourstocollect > 4500:
            hourstocollect = 4500
        if hourstocollect < 0 or hourstocollect == 0:
            flash("Can't collect 0 hours. Please input a number equal to 1 or higher")
            return redirect("/collectdata")
        
        ###############################################################################################
        #Collecting data from Tibber and saving it in lists that are merged and made into a tuple list
        ###############################################################################################
        account=tibber.Account(tibber_token)
        home = account.homes[0]
        hour_data = home.fetch_consumption("HOURLY", last=hourstocollect)
       
        start=[]
        stop=[]
        price=[]
        cons=[]
        cost=[]

        for hour in hour_data:
            data1=(hour.from_time)
            data2=(hour.to_time)
            data3=(f"{hour.unit_price}{hour.currency}")
            data4=(hour.consumption)
            data5=(hour.cost)
            start.append(data1)
            stop.append(data2)
            price.append(data3)
            cons.append(data4)
            cost.append(data5)        

        #Creating a list of only dates 
        date = [d[:-19] for d in start]

        #Removing unnecessary info from the date variable
        start = [d[:-13] for d in start]
        stop = [d[:-13] for d in stop]

        #Removing SEK from the list containing prices
        price = ([s.replace('SEK', '') for s in price])

        ############################################################################
        # Checking which data to insert and which to update in the database table
        ############################################################################

        #Merging all lists of data to one tuple list and transforming it into a dataframe
        def merge(date,stop,price,cons,cost,start):
            merged_list = [(date[i], stop[i], price[i], cons[i], cost[i],start[i]) for i in range(0, len(start))]
            return merged_list
        collected_data = merge(date,stop,price,cons,cost,start)

        df_collected_data = pd.DataFrame((collected_data), columns=['date', 'stop', 'price', 'cons', 'cost', 'start'])

        #Getting all start times data from the database as a tuple and transforming it into a list and a dataframe
        starttimes_tup=get_all_starttimes()
        starttimes  = [tupleObj[0] for tupleObj in starttimes_tup]
        df_starttimes = pd.DataFrame((starttimes_tup), columns=['start'])

        #Checking which start times that are already in the database and are to be updated and which are new and are to be inserted
        df_collected_to_be_updated = df_collected_data.query('start in @starttimes')
        df_collected_to_be_inserted = df_collected_data.query('start not in @starttimes')

        #Transforming dataframes into tuple lists
        collected_to_be_updated = list(df_collected_to_be_updated.itertuples(index=False, name=None))
        collected_to_be_inserted = list(df_collected_to_be_inserted.itertuples(index=False, name=None))

        #Updating the database
        conn = get_db_connection()
        cur = conn.cursor()
        for d in collected_to_be_updated:
            cur.execute("UPDATE collecteddata set date = (%s)::text, stop = (%s)::text, price = (%s), consumption = (%s), cost = (%s) WHERE start = (%s)::text", d)
        conn.commit()
        cur.close()
        conn.close()   

        #Inserting data into the database
        conn = get_db_connection()
        cur = conn.cursor()
        for d in collected_to_be_inserted:
            cur.execute("INSERT INTO collecteddata(date, stop, price, consumption, cost, start) VALUES(%s,%s,%s,%s,%s,%s)", d)
        conn.commit()
        cur.close()
        conn.close()

        ###################################################################
        #Creating a tuple list to be inserted into the consumption table
        ###################################################################

        #Checking which start times that are already in the consumption table
        starttimes_tup_cons=get_all_starttimes_cons()
        starttimes_cons = [tupleObj[0] for tupleObj in starttimes_tup_cons]

        #Creating new lists of consumption connected to the house (setting value same as raw data ) and the EV (setting value to 0)
        consumption_ev = cons.copy() 

        for i in range(len(consumption_ev)):
            if consumption_ev[i] != '':
                consumption_ev[i] = '0'

        consumption_house = cons.copy()

        #Merging all lists to one tuple list and transforming it into a dataframe
        def merger(date,start,consumption_house,consumption_ev):
            merger_list = [(date[i], start[i], consumption_house[i], consumption_ev[i]) for i in range(0, len(start))]
            return merger_list
        collected_data2 = merger(date, start,consumption_house,consumption_ev)

        df_collected_data2 = pd.DataFrame((collected_data2), columns=['date', 'start', 'consumption_house', 'consumption_ev'])

        #Checking which start times that are new and are to be inserted        
        df_collected_to_be_inserted2 = df_collected_data2.query('start not in @starttimes_cons')

        collected_to_be_inserted2 = list(df_collected_to_be_inserted2.itertuples(index=False, name=None))

        #Inserting data into database
        conn = get_db_connection()
        cur = conn.cursor()
        for d in collected_to_be_inserted2:
            cur.execute("INSERT INTO consumption(date, start,consumption_house,consumption_ev) VALUES(%s,%s,%s,%s)", d)
        conn.commit()
        cur.close()
        conn.close()

        ###############################################################
        #Creating a tuple list to be inserted into the cost table
        ###############################################################

        #Checking which start times that are already in the cost table
        starttimes_tup_cost=get_all_starttimes_cost()
        starttimes_cost  = [tupleObj[0] for tupleObj in starttimes_tup_cost]

        #Creating new lists of cost connected to the house (setting value same as raw data ) and the EV (setting value to 0)
        cost_ev = cost.copy() 

        for i in range(len(cost_ev)):
            if cost_ev[i] != '':
                cost_ev[i] = '0'

        cost_house = cost.copy()

        #Merging all lists to one tuple list and transforming it into a dataframe
        def mergers(date,start,cost_house,cost_ev):
            mergers_list = [(date[i], start[i], cost_house[i], cost_ev[i]) for i in range(0, len(start))]
            return mergers_list
        collected_data3 = mergers(date, start,cost_house,cost_ev)

        df_collected_data3 = pd.DataFrame((collected_data3), columns=['date', 'start', 'cost_house', 'cost_ev'])

        #Checking which start times that are new and are to be inserted        
        df_collected_to_be_inserted3 = df_collected_data3.query('start not in @starttimes_cost')

        collected_to_be_inserted3 = list(df_collected_to_be_inserted3.itertuples(index=False, name=None))

        #Inserting data into database
        conn = get_db_connection()
        cur = conn.cursor()
        for d in collected_to_be_inserted3:
            cur.execute("INSERT INTO cost(date, start,cost_house,cost_ev) VALUES(%s,%s,%s,%s)", d)
        conn.commit()
        cur.close()
        conn.close()

        data = tuple(sorted(collected_data, reverse=True))

        dayscollected = hourstocollect / 24
        
    return render_template("/datacollected.html", data=data, hourstocollect=hourstocollect, dayscollected=dayscollected)

@app.route("/updateday", methods=["GET", "POST"])
def updateday():

    global chosendate

    if request.method == "GET":

        #Getting start times from the consumption table and finding newest date
        starttimes_tup = get_all_starttimes()
        starttimes  = [tupleObj[0] for tupleObj in starttimes_tup]

        #Adjusting the dates and time into year and month
        dates = [d[:-6] for d in starttimes]

        #Removing duplicates and sorting
        dates_list = list(dict.fromkeys(dates))
        dates_list.sort(reverse=True)
        chosendate = dates_list[0]

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM collecteddata WHERE date = (%s) ORDER BY start ASC",
                    (chosendate,))
        data1 = cur.fetchall()
        cur.close()
        conn.close()

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM consumption WHERE date = (%s) ORDER BY start ASC",
                    (chosendate,))
        data2 = cur.fetchall()
        cur.close()
        conn.close()

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM cost WHERE date = (%s) ORDER BY start ASC",
                    (chosendate,))
        data3 = cur.fetchall()
        cur.close()
        conn.close()

        #Flashing message if there is no date
        if not data1:
            flash("There is no data for chosendate. Please collect data first")
            return redirect("/updateday")

        #Transforming the lists into dataframes, droping unnecessary colums, transforming strings to floats, merger dataframes, rounding the figures to two decimals and transforming the dataframe to a list
        df_data1 = pd.DataFrame((data1), columns=('date', 'start', 'stop', 'price', 'consumption', 'cost'))
        df_data2 = pd.DataFrame((data2), columns=('date', 'start', 'consumption_house', 'consumption_ev'))
        df_data3 = pd.DataFrame((data3), columns=('date', 'start', 'cost_house', 'cost_ev'))
        df_data2 = df_data2.drop(columns=['date'])
        df_data3 = df_data3.drop(columns=['date'])
        df_data1_2 = pd.merge(df_data1, df_data2, on="start")
        df_data1_3 = pd.merge(df_data1_2, df_data3, on="start")
        df_data1_3[["date2", "time"]] = df_data1_3.start.str.split("T", expand=True)
        df_data1_3[["hour", "min"]] = df_data1_3.time.str.split(":", expand=True)
        df_data1_3 = df_data1_3.drop(columns=['date2', 'time', 'min'])
        data = df_data1_3.values.tolist()

        #Adjusting the dataframe and aggregating the data by date
        df_aggr1 = df_data1_3.drop(columns=['start','stop', 'price'])
        df_aggr1['consumption'] = df_aggr1['consumption'].astype(float)
        df_aggr1['cost'] = df_aggr1['cost'].astype(float)
        df_aggr1['consumption_house'] = df_aggr1['consumption_house'].astype(float)
        df_aggr1['consumption_ev'] = df_aggr1['consumption_ev'].astype(float)
        df_aggr1['cost_house'] = df_aggr1['cost_house'].astype(float)
        df_aggr1['cost_ev'] = df_aggr1['cost_ev'].astype(float)
        df_aggr2 = df_aggr1.groupby(['date'], as_index=False).sum()
        rounded_df_aggr2 = df_aggr2.round(decimals=2)
        aggr = rounded_df_aggr2.values.tolist()

    if request.method == "POST":

        req = request.form

        action=req["action"]

        if action[0:4] == "View":

            #Creating a variable from the form data
            chosendate = req["chosendate2"]

            date_time = datetime.datetime.now()
            today = date_time.strftime("%Y-%m-%d")

            #Flashing message if date is not applicable
            if chosendate > today or chosendate == "":
                flash("Please select today or an earlier date")
                return redirect("/updateday")        

            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("SELECT * FROM collecteddata WHERE date = (%s) ORDER BY start ASC",
                        (chosendate,))
            data1 = cur.fetchall()
            cur.close()
            conn.close()

            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("SELECT * FROM consumption WHERE date = (%s) ORDER BY start ASC",
                        (chosendate,))
            data2 = cur.fetchall()
            cur.close()
            conn.close()

            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("SELECT * FROM cost WHERE date = (%s) ORDER BY start ASC",
                        (chosendate,))
            data3 = cur.fetchall()
            cur.close()
            conn.close()

            #Flashing message if there is no date
            if not data1:
                flash("There is no data for selected date. Please collect data first")
                return redirect("/updateday")

            #Transforming the lists into dataframes, droping unnecessary colums, transforming strings to floats, merger dataframes, rounding the figures to two decimals and transforming the dataframe to a list
            df_data1 = pd.DataFrame((data1), columns=('date', 'start', 'stop', 'price', 'consumption', 'cost'))
            df_data2 = pd.DataFrame((data2), columns=('date', 'start', 'consumption_house', 'consumption_ev'))
            df_data3 = pd.DataFrame((data3), columns=('date', 'start', 'cost_house', 'cost_ev'))
            df_data2 = df_data2.drop(columns=['date'])
            df_data3 = df_data3.drop(columns=['date'])
            df_data1_2 = pd.merge(df_data1, df_data2, on="start")
            df_data1_3 = pd.merge(df_data1_2, df_data3, on="start")
            df_data1_3[["date2", "time"]] = df_data1_3.start.str.split("T", expand=True)
            df_data1_3[["hour", "min"]] = df_data1_3.time.str.split(":", expand=True)
            df_data1_3 = df_data1_3.drop(columns=['date2', 'time', 'min'])
            data = df_data1_3.values.tolist()

            #Adjusting the dataframe and aggregating the data by date
            df_aggr1 = df_data1_3.drop(columns=['start','stop', 'price'])
            df_aggr1['consumption'] = df_aggr1['consumption'].astype(float)
            df_aggr1['cost'] = df_aggr1['cost'].astype(float)
            df_aggr1['consumption_house'] = df_aggr1['consumption_house'].astype(float)
            df_aggr1['consumption_ev'] = df_aggr1['consumption_ev'].astype(float)
            df_aggr1['cost_house'] = df_aggr1['cost_house'].astype(float)
            df_aggr1['cost_ev'] = df_aggr1['cost_ev'].astype(float)
            df_aggr2 = df_aggr1.groupby(['date'], as_index=False).sum()
            rounded_df_aggr2 = df_aggr2.round(decimals=2)
            aggr = rounded_df_aggr2.values.tolist()

        if action[0:4] == "Upda":

            chosendate = req["chosendate"] 

            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("SELECT * FROM collecteddata WHERE date = (%s) ORDER BY start ASC",
                        (chosendate,))
            data1 = cur.fetchall()
            cur.close()
            conn.close()

            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("SELECT * FROM consumption WHERE date = (%s) ORDER BY start ASC",
                        (chosendate,))
            data2 = cur.fetchall()
            cur.close()
            conn.close()

            #Creating variables from the form dictionary
            if req.get("cons_ev00") != None:            
                cons_ev00 = float(req["cons_ev00"])           
            if req.get("cons_ev01") != None: 
                cons_ev01 = float(req["cons_ev01"])                
            if req.get("cons_ev02") != None: 
                cons_ev02 = float(req["cons_ev02"])                  
            if req.get("cons_ev03") != None: 
                cons_ev03 = float(req["cons_ev03"])               
            if req.get("cons_ev04") != None: 
                cons_ev04 = float(req["cons_ev04"])                 
            if req.get("cons_ev05") != None: 
                cons_ev05 = float(req["cons_ev05"])                 
            if req.get("cons_ev06") != None: 
                cons_ev06 = float(req["cons_ev06"])                
            if req.get("cons_ev07") != None: 
                cons_ev07 = float(req["cons_ev07"])               
            if req.get("cons_ev08") != None: 
                cons_ev08 = float(req["cons_ev08"])                
            if req.get("cons_ev09") != None: 
                cons_ev09 = float(req["cons_ev09"])                
            if req.get("cons_ev10") != None: 
                cons_ev10 = float(req["cons_ev10"])                 
            if req.get("cons_ev11") != None: 
                cons_ev11 = float(req["cons_ev11"])                 
            if req.get("cons_ev12") != None: 
                cons_ev12 = float(req["cons_ev12"])                
            if req.get("cons_ev13") != None: 
                cons_ev13 = float(req["cons_ev13"])                 
            if req.get("cons_ev14") != None: 
                cons_ev14 = float(req["cons_ev14"])                 
            if req.get("cons_ev15") != None: 
                cons_ev15 = float(req["cons_ev15"])                
            if req.get("cons_ev16") != None: 
                cons_ev16 = float(req["cons_ev16"])                 
            if req.get("cons_ev17") != None: 
                cons_ev17 = float(req["cons_ev17"])                 
            if req.get("cons_ev18") != None: 
                cons_ev18 = float(req["cons_ev18"])                 
            if req.get("cons_ev19") != None:
                cons_ev19 = float(req["cons_ev19"])
            if req.get("cons_ev20") != None:           
                cons_ev20 = float(req["cons_ev20"])
            if req.get("cons_ev21") != None:
                cons_ev21 = float(req["cons_ev21"])
            if req.get("cons_ev22") != None:
                cons_ev22 = float(req["cons_ev22"])
            if req.get("cons_ev23") != None:                
                cons_ev23 = float(req["cons_ev23"])

            if req.get("cons00") != None:            
                cons00 = float(req["cons00"])
            if req.get("cons01") != None: 
                cons01 = float(req["cons01"])             
            if req.get("cons02") != None: 
                cons02 = float(req["cons02"])               
            if req.get("cons03") != None: 
                cons03 = float(req["cons03"])                 
            if req.get("cons04") != None: 
                cons04 = float(req["cons04"])                
            if req.get("cons05") != None: 
                cons05 = float(req["cons05"])               
            if req.get("cons06") != None: 
                cons06 = float(req["cons06"])                
            if req.get("cons07") != None: 
                cons07 = float(req["cons07"])               
            if req.get("cons08") != None: 
                cons08 = float(req["cons08"])               
            if req.get("cons09") != None: 
                cons09 = float(req["cons09"])                 
            if req.get("cons10") != None: 
                cons10 = float(req["cons10"])                
            if req.get("cons11") != None: 
                cons11 = float(req["cons11"])               
            if req.get("cons12") != None: 
                cons12 = float(req["cons12"])                 
            if req.get("cons13") != None: 
                cons13 = float(req["cons13"])                
            if req.get("cons14") != None: 
                cons14 = float(req["cons14"])                 
            if req.get("cons15") != None: 
                cons15 = float(req["cons15"])               
            if req.get("cons16") != None: 
                cons16 = float(req["cons16"])                
            if req.get("cons17") != None: 
                cons17 = float(req["cons17"])                
            if req.get("cons18") != None: 
                cons18 = float(req["cons18"])             
            if req.get("cons19") != None:
                cons19 = float(req["cons19"])
            if req.get("cons20") != None:           
                cons20 = float(req["cons20"])
            if req.get("cons21") != None:
                cons21 = float(req["cons21"])
            if req.get("cons22") != None:
                cons22 = float(req["cons22"])
            if req.get("cons23") != None:                
                cons23 = float(req["cons23"])   

            start00 = req.get("start00")
            start01 = req.get("start01")
            start02 = req.get("start02")
            start03 = req.get("start03")
            start04 = req.get("start04")
            start05 = req.get("start05")
            start06 = req.get("start06")
            start07 = req.get("start07")
            start08 = req.get("start08")
            start09 = req.get("start09")
            start10 = req.get("start10")
            start11 = req.get("start11")
            start12 = req.get("start12")
            start13 = req.get("start13")
            start14 = req.get("start14")
            start15 = req.get("start15")
            start16 = req.get("start16")
            start17 = req.get("start17")
            start18 = req.get("start18")
            start19 = req.get("start19")
            start20 = req.get("start20")
            start21 = req.get("start21")
            start22 = req.get("start22")
            start23 = req.get("start23")

            if start00 != None:
                cons_house00 = round((cons00 - cons_ev00), 3)
                cost00 = round((float(data1[0][3])*cons00), 8)
                cost_house00 = round((float(data1[0][3])*cons_house00), 3)
                cost_ev00 = round((float(data1[0][3])*cons_ev00), 3)
            if start01 != None:      
                cons_house01 = round((cons01 - cons_ev01), 3)
                cost01 = round((float(data1[1][3])*cons01), 8)
                cost_house01 = round((float(data1[1][3])*cons_house01), 3)
                cost_ev01 = round((float(data1[1][3])*cons_ev01), 3)
            if start02 != None:
                cons_house02 = round((cons02 - cons_ev02), 3)
                cost02 = round((float(data1[2][3])*cons02), 8)           
                cost_house02 = round((float(data1[2][3])*cons_house02), 3)
                cost_ev02 = round((float(data1[2][3])*cons_ev02), 3)
            if start03 != None:
                cons_house03 = round((cons03 - cons_ev03), 3)
                cost03 = round((float(data1[3][3])*cons03), 8)                                 
                cost_house03 = round((float(data1[3][3])*cons_house03), 3)
                cost_ev03 = round((float(data1[3][3])*cons_ev03), 3)
            if start04 != None:          
                cons_house04 = round((cons04 - cons_ev04), 3)
                cost04 = round((float(data1[4][3])*cons04), 8)                       
                cost_house04 = round((float(data1[4][3])*cons_house04), 3)
                cost_ev04 = round((float(data1[4][3])*cons_ev04), 3)                
            if start05 != None:   
                cons_house05 = round((cons05- cons_ev05), 3)
                cost05 = round((float(data1[5][3])*cons05), 8)                               
                cost_house05 = round((float(data1[5][3])*cons_house05), 3)
                cost_ev05 = round((float(data1[5][3])*cons_ev05), 3)                 
            if start06 != None:
                cons_house06 = round((cons06 - cons_ev06), 3)
                cost06= round((float(data1[6][3])*cons06), 8)                                  
                cost_house06 = round((float(data1[6][3])*cons_house06), 3)
                cost_ev06 = round((float(data1[6][3])*cons_ev06), 3)                 
            if start07 != None:  
                cons_house07 = round((cons07 - cons_ev07), 3)
                cost07 = round((float(data1[7][3])*cons07), 8)                                
                cost_house07 = round((float(data1[7][3])*cons_house07), 3)
                cost_ev07 = round((float(data1[7][3])*cons_ev07), 3)                 
            if start08 != None:    
                cons_house08 = round((cons08 - cons_ev08), 3)
                cost08 = round((float(data1[8][3])*cons08), 8)                              
                cost_house08 = round((float(data1[8][3])*cons_house08), 3)
                cost_ev08 = round((float(data1[8][3])*cons_ev08), 3)                 
            if start09 != None:   
                cons_house09 = round((cons09 - cons_ev09), 3)
                cost09 = round((float(data1[9][3])*cons09), 8)                               
                cost_house09 = round((float(data1[9][3])*cons_house09), 3)
                cost_ev09 = round((float(data1[9][3])*cons_ev09), 3)                 
            if start10 != None:    
                cons_house10 = round((cons10 - cons_ev10), 3)
                cost10 = round((float(data1[10][3])*cons10), 8)                              
                cost_house10 = round((float(data1[10][3])*cons_house10), 3)
                cost_ev10 = round((float(data1[10][3])*cons_ev10), 3)                 
            if start11 != None:   
                cons_house11 = round((cons11 - cons_ev11), 3)
                cost11 = round((float(data1[11][3])*cons11), 8)                               
                cost_house11 = round((float(data1[11][3])*cons_house11), 3)
                cost_ev11 = round((float(data1[11][3])*cons_ev11), 3)                 
            if start12 != None: 
                cons_house12 = round((cons12 - cons_ev12), 3)
                cost12 = round((float(data1[12][3])*cons12), 8)                                 
                cost_house12 = round((float(data1[12][3])*cons_house12), 3)
                cost_ev12 = round((float(data1[12][3])*cons_ev12), 3)                  
            if start13 != None: 
                cons_house13 = round((cons13 - cons_ev13), 3)
                cost13 = round((float(data1[13][3])*cons13), 8)                                 
                cost_house13= round((float(data1[13][3])*cons_house13), 3)
                cost_ev13 = round((float(data1[13][3])*cons_ev13), 3)                  
            if start14 != None:   
                cons_house14 = round((cons14 - cons_ev14), 3)
                cost14 = round((float(data1[14][3])*cons14), 8)                               
                cost_house14 = round((float(data1[14][3])*cons_house14), 3)
                cost_ev14 = round((float(data1[14][3])*cons_ev14), 3)                  
            if start15 != None:  
                cons_house15 = round((cons15 - cons_ev15), 3)
                cost15 = round((float(data1[15][3])*cons15), 8)                                
                cost_house15 = round((float(data1[15][3])*cons_house15), 3)
                cost_ev15 = round((float(data1[15][3])*cons_ev15), 3)                  
            if start16 != None:  
                cons_house16 = round((cons16 - cons_ev16), 3)
                cost16 = round((float(data1[16][3])*cons16), 8)                                
                cost_house16 = round((float(data1[16][3])*cons_house16), 3)
                cost_ev16 = round((float(data1[16][3])*cons_ev16), 3)                  
            if start17 != None:    
                cons_house17 = round((cons17 - cons_ev17), 3)
                cost17 = round((float(data1[17][3])*cons17), 8)                              
                cost_house17 = round((float(data1[17][3])*cons_house17), 3)
                cost_ev17 = round((float(data1[17][3])*cons_ev17), 3)                  
            if start18 != None:  
                cons_house18 = round((cons18 - cons_ev18), 3)
                cost18 = round((float(data1[18][3])*cons18), 8)                                
                cost_house18 = round((float(data1[18][3])*cons_house18), 3)
                cost_ev18 = round((float(data1[18][3])*cons_ev18), 3)                  
            if start19 != None:
                cons_house19 = round((cons19 - cons_ev19), 3)
                cost19 = round((float(data1[19][3])*cons19), 8)                  
                cost_house19 = round((float(data1[19][3])*cons_house19), 3)
                cost_ev19 = round((float(data1[19][3])*cons_ev19), 3)                  
            if start20 != None:
                cons_house20 = round((cons20 - cons_ev20), 3)
                cost20 = round((float(data1[20][3])*cons20), 8)  
                cost_house20 = round((float(data1[20][3])*cons_house20), 3)
                cost_ev20 = round((float(data1[20][3])*cons_ev20), 3)                 
            if start21 != None:
                cons_house21 = round((cons21 - cons_ev21), 3)
                cost21 = round((float(data1[21][3])*cons21), 8)                  
                cost_house21 = round((float(data1[21][3])*cons_house21), 3)
                cost_ev21 = round((float(data1[21][3])*cons_ev21), 3)                 
            if start22 != None:
                cons_house22 = round((cons22 - cons_ev22), 3)
                cost22 = round((float(data1[22][3])*cons22), 8)                  
                cost_house22 = round((float(data1[22][3])*cons_house22), 3)
                cost_ev22 = round((float(data1[22][3])*cons_ev22), 3)                 
            if start23 != None:
                cons_house23 = round((cons23 - cons_ev23), 3)
                cost23 = round((float(data1[23][3])*cons23), 8)                  
                cost_house23 = round((float(data1[23][3])*cons_house23), 3)
                cost_ev23 = round((float(data1[23][3])*cons_ev23), 3)                 

            if start00 != None:

                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("UPDATE collecteddata SET consumption = (%s), cost = (%s)" "WHERE start = (%s)", [cons00, cost00, start00]);
                conn.commit()
                cur.close()
                conn.close()

                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("UPDATE consumption SET consumption_ev = (%s), consumption_house = (%s)" "WHERE start = (%s)", [cons_ev00, cons_house00, start00]);
                conn.commit()
                cur.close()
                conn.close()

                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("UPDATE cost SET cost_ev = (%s), cost_house = (%s)" "WHERE start = (%s)", [cost_ev00, cost_house00, start00]);
                conn.commit()
                cur.close()
                conn.close()

            if start01 != None:

                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("UPDATE collecteddata SET consumption = (%s), cost = (%s)" "WHERE start = (%s)", [cons01, cost01, start01]);
                conn.commit()
                cur.close()
                conn.close()

                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("UPDATE consumption SET consumption_ev = (%s), consumption_house = (%s)" "WHERE start = (%s)", [cons_ev01, cons_house01, start01]);
                conn.commit()
                cur.close()
                conn.close()

                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("UPDATE cost SET cost_ev = (%s), cost_house = (%s)" "WHERE start = (%s)", [cost_ev01, cost_house01, start01]);
                conn.commit()
                cur.close()
                conn.close()

            if start02 != None:

                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("UPDATE collecteddata SET consumption = (%s), cost = (%s)" "WHERE start = (%s)", [cons02, cost02, start02]);
                conn.commit()
                cur.close()
                conn.close()
                
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("UPDATE consumption SET consumption_ev = (%s), consumption_house = (%s)" "WHERE start = (%s)", [cons_ev02, cons_house02, start02]);
                conn.commit()
                cur.close()
                conn.close()

                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("UPDATE cost SET cost_ev = (%s), cost_house = (%s)" "WHERE start = (%s)", [cost_ev02, cost_house02, start02]);
                conn.commit()
                cur.close()
                conn.close()

            if start03 != None:

                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("UPDATE collecteddata SET consumption = (%s), cost = (%s)" "WHERE start = (%s)", [cons03, cost03, start03]);
                conn.commit()
                cur.close()
                conn.close()

                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("UPDATE consumption SET consumption_ev = (%s), consumption_house = (%s)" "WHERE start = (%s)", [cons_ev03, cons_house03, start03]);
                conn.commit()
                cur.close()
                conn.close()

                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("UPDATE cost SET cost_ev = (%s), cost_house = (%s)" "WHERE start = (%s)", [cost_ev03, cost_house03, start03]);
                conn.commit()
                cur.close()
                conn.close()

            if start04 != None:

                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("UPDATE collecteddata SET consumption = (%s), cost = (%s)" "WHERE start = (%s)", [cons04, cost04, start04]);
                conn.commit()
                cur.close()
                conn.close()
 
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("UPDATE consumption SET consumption_ev = (%s), consumption_house = (%s)" "WHERE start = (%s)", [cons_ev04, cons_house04, start04]);
                conn.commit()
                cur.close()
                conn.close()

                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("UPDATE cost SET cost_ev = (%s), cost_house = (%s)" "WHERE start = (%s)", [cost_ev04, cost_house04, start04]);
                conn.commit()
                cur.close()
                conn.close()

            if start05 != None:

                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("UPDATE collecteddata SET consumption = (%s), cost = (%s)" "WHERE start = (%s)", [cons05, cost05, start05]);
                conn.commit()
                cur.close()
                conn.close()
 
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("UPDATE consumption SET consumption_ev = (%s), consumption_house = (%s)" "WHERE start = (%s)", [cons_ev05, cons_house05, start05]);
                conn.commit()
                cur.close()
                conn.close()

                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("UPDATE cost SET cost_ev = (%s), cost_house = (%s)" "WHERE start = (%s)", [cost_ev05, cost_house05, start05]);
                conn.commit()
                cur.close()
                conn.close()

            if start06 != None:

                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("UPDATE collecteddata SET consumption = (%s), cost = (%s)" "WHERE start = (%s)", [cons06, cost06, start06]);
                conn.commit()
                cur.close()
                conn.close()
 
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("UPDATE consumption SET consumption_ev = (%s), consumption_house = (%s)" "WHERE start = (%s)", [cons_ev06, cons_house06, start06]);
                conn.commit()
                cur.close()
                conn.close()

                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("UPDATE cost SET cost_ev = (%s), cost_house = (%s)" "WHERE start = (%s)", [cost_ev06, cost_house06, start06]);
                conn.commit()
                cur.close()
                conn.close()

            if start07 != None:

                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("UPDATE collecteddata SET consumption = (%s), cost = (%s)" "WHERE start = (%s)", [cons07, cost07, start07]);
                conn.commit()
                cur.close()
                conn.close()
 
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("UPDATE consumption SET consumption_ev = (%s), consumption_house = (%s)" "WHERE start = (%s)", [cons_ev07, cons_house07, start07]);
                conn.commit()
                cur.close()
                conn.close()

                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("UPDATE cost SET cost_ev = (%s), cost_house = (%s)" "WHERE start = (%s)", [cost_ev07, cost_house07, start07]);
                conn.commit()
                cur.close()
                conn.close()

            if start08 != None:

                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("UPDATE collecteddata SET consumption = (%s), cost = (%s)" "WHERE start = (%s)", [cons08, cost08, start08]);
                conn.commit()
                cur.close()
                conn.close()
 
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("UPDATE consumption SET consumption_ev = (%s), consumption_house = (%s)" "WHERE start = (%s)", [cons_ev08, cons_house08, start08]);
                conn.commit()
                cur.close()
                conn.close()

                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("UPDATE cost SET cost_ev = (%s), cost_house = (%s)" "WHERE start = (%s)", [cost_ev08, cost_house08, start08]);
                conn.commit()
                cur.close()
                conn.close()

            if start09 != None:

                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("UPDATE collecteddata SET consumption = (%s), cost = (%s)" "WHERE start = (%s)", [cons09, cost09, start09]);
                conn.commit()
                cur.close()
                conn.close()
 
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("UPDATE consumption SET consumption_ev = (%s), consumption_house = (%s)" "WHERE start = (%s)", [cons_ev09, cons_house09, start09]);
                conn.commit()
                cur.close()
                conn.close()

                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("UPDATE cost SET cost_ev = (%s), cost_house = (%s)" "WHERE start = (%s)", [cost_ev09, cost_house09, start09]);
                conn.commit()
                cur.close()
                conn.close()

            if start10 != None:

                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("UPDATE collecteddata SET consumption = (%s), cost = (%s)" "WHERE start = (%s)", [cons10, cost10, start10]);
                conn.commit()
                cur.close()
                conn.close()
 
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("UPDATE consumption SET consumption_ev = (%s), consumption_house = (%s)" "WHERE start = (%s)", [cons_ev10, cons_house10, start10]);
                conn.commit()
                cur.close()
                conn.close()

                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("UPDATE cost SET cost_ev = (%s), cost_house = (%s)" "WHERE start = (%s)", [cost_ev10, cost_house10, start10]);
                conn.commit()
                cur.close()
                conn.close()

            if start11 != None:

                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("UPDATE collecteddata SET consumption = (%s), cost = (%s)" "WHERE start = (%s)", [cons11, cost11, start11]);
                conn.commit()
                cur.close()
                conn.close()
 
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("UPDATE consumption SET consumption_ev = (%s), consumption_house = (%s)" "WHERE start = (%s)", [cons_ev11, cons_house11, start11]);
                conn.commit()
                cur.close()
                conn.close()

                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("UPDATE cost SET cost_ev = (%s), cost_house = (%s)" "WHERE start = (%s)", [cost_ev11, cost_house11, start11]);
                conn.commit()
                cur.close()
                conn.close()

            if start12 != None:

                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("UPDATE collecteddata SET consumption = (%s), cost = (%s)" "WHERE start = (%s)", [cons12, cost12, start12]);
                conn.commit()
                cur.close()
                conn.close()
 
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("UPDATE consumption SET consumption_ev = (%s), consumption_house = (%s)" "WHERE start = (%s)", [cons_ev12, cons_house12, start12]);
                conn.commit()
                cur.close()
                conn.close()

                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("UPDATE cost SET cost_ev = (%s), cost_house = (%s)" "WHERE start = (%s)", [cost_ev12, cost_house12, start12]);
                conn.commit()
                cur.close()
                conn.close()

            if start13 != None:

                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("UPDATE collecteddata SET consumption = (%s), cost = (%s)" "WHERE start = (%s)", [cons13, cost13, start13]);
                conn.commit()
                cur.close()
                conn.close()
 
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("UPDATE consumption SET consumption_ev = (%s), consumption_house = (%s)" "WHERE start = (%s)", [cons_ev13, cons_house13, start13]);
                conn.commit()
                cur.close()
                conn.close()

                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("UPDATE cost SET cost_ev = (%s), cost_house = (%s)" "WHERE start = (%s)", [cost_ev13, cost_house13, start13]);
                conn.commit()
                cur.close()
                conn.close()

            if start14 != None:

                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("UPDATE collecteddata SET consumption = (%s), cost = (%s)" "WHERE start = (%s)", [cons14, cost14, start14]);
                conn.commit()
                cur.close()
                conn.close()
 
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("UPDATE consumption SET consumption_ev = (%s), consumption_house = (%s)" "WHERE start = (%s)", [cons_ev14, cons_house14, start14]);
                conn.commit()
                cur.close()
                conn.close()

                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("UPDATE cost SET cost_ev = (%s), cost_house = (%s)" "WHERE start = (%s)", [cost_ev14, cost_house14, start14]);
                conn.commit()
                cur.close()
                conn.close()

            if start15 != None:

                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("UPDATE collecteddata SET consumption = (%s), cost = (%s)" "WHERE start = (%s)", [cons15, cost15, start15]);
                conn.commit()
                cur.close()
                conn.close()
 
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("UPDATE consumption SET consumption_ev = (%s), consumption_house = (%s)" "WHERE start = (%s)", [cons_ev15, cons_house15, start15]);
                conn.commit()
                cur.close()
                conn.close()

                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("UPDATE cost SET cost_ev = (%s), cost_house = (%s)" "WHERE start = (%s)", [cost_ev15, cost_house15, start15]);
                conn.commit()
                cur.close()
                conn.close()

            if start16 != None:

                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("UPDATE collecteddata SET consumption = (%s), cost = (%s)" "WHERE start = (%s)", [cons16, cost16, start16]);
                conn.commit()
                cur.close()
                conn.close()
 
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("UPDATE consumption SET consumption_ev = (%s), consumption_house = (%s)" "WHERE start = (%s)", [cons_ev16, cons_house16, start16]);
                conn.commit()
                cur.close()
                conn.close()

                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("UPDATE cost SET cost_ev = (%s), cost_house = (%s)" "WHERE start = (%s)", [cost_ev16, cost_house16, start16]);
                conn.commit()
                cur.close()
                conn.close()

            if start17 != None:

                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("UPDATE collecteddata SET consumption = (%s), cost = (%s)" "WHERE start = (%s)", [cons17, cost17, start17]);
                conn.commit()
                cur.close()
                conn.close()
 
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("UPDATE consumption SET consumption_ev = (%s), consumption_house = (%s)" "WHERE start = (%s)", [cons_ev17, cons_house17, start17]);
                conn.commit()
                cur.close()
                conn.close()

                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("UPDATE cost SET cost_ev = (%s), cost_house = (%s)" "WHERE start = (%s)", [cost_ev17, cost_house17, start17]);
                conn.commit()
                cur.close()
                conn.close()

            if start18 != None:

                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("UPDATE collecteddata SET consumption = (%s), cost = (%s)" "WHERE start = (%s)", [cons18, cost18, start18]);
                conn.commit()
                cur.close()
                conn.close()
 
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("UPDATE consumption SET consumption_ev = (%s), consumption_house = (%s)" "WHERE start = (%s)", [cons_ev18, cons_house18, start18]);
                conn.commit()
                cur.close()
                conn.close()

                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("UPDATE cost SET cost_ev = (%s), cost_house = (%s)" "WHERE start = (%s)", [cost_ev18, cost_house18, start18]);
                conn.commit()
                cur.close()
                conn.close()

            if start19 != None:

                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("UPDATE collecteddata SET consumption = (%s), cost = (%s)" "WHERE start = (%s)", [cons19, cost19, start19]);
                conn.commit()
                cur.close()
                conn.close()
 
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("UPDATE consumption SET consumption_ev = (%s), consumption_house = (%s)" "WHERE start = (%s)", [cons_ev19, cons_house19, start19]);
                conn.commit()
                cur.close()
                conn.close()

                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("UPDATE cost SET cost_ev = (%s), cost_house = (%s)" "WHERE start = (%s)", [cost_ev19, cost_house19, start19]);
                conn.commit()
                cur.close()
                conn.close()

            if start20 != None:

                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("UPDATE collecteddata SET consumption = (%s), cost = (%s)" "WHERE start = (%s)", [cons20, cost20, start20]);
                conn.commit()
                cur.close()
                conn.close()
 
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("UPDATE consumption SET consumption_ev = (%s), consumption_house = (%s)" "WHERE start = (%s)", [cons_ev20, cons_house20, start20]);
                conn.commit()
                cur.close()
                conn.close()

                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("UPDATE cost SET cost_ev = (%s), cost_house = (%s)" "WHERE start = (%s)", [cost_ev20, cost_house20, start20]);
                conn.commit()
                cur.close()
                conn.close()

            if start21 != None:

                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("UPDATE collecteddata SET consumption = (%s), cost = (%s)" "WHERE start = (%s)", [cons21, cost21, start21]);
                conn.commit()
                cur.close()
                conn.close()
 
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("UPDATE consumption SET consumption_ev = (%s), consumption_house = (%s)" "WHERE start = (%s)", [cons_ev21, cons_house21, start21]);
                conn.commit()
                cur.close()
                conn.close()
                
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("UPDATE cost SET cost_ev = (%s), cost_house = (%s)" "WHERE start = (%s)", [cost_ev21, cost_house21, start21]);
                conn.commit()
                cur.close()
                conn.close()

            if start22 != None:

                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("UPDATE collecteddata SET consumption = (%s), cost = (%s)" "WHERE start = (%s)", [cons22, cost22, start22]);
                conn.commit()
                cur.close()
                conn.close()
 
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("UPDATE consumption SET consumption_ev = (%s), consumption_house = (%s)" "WHERE start = (%s)", [cons_ev22, cons_house22, start22]);
                conn.commit()
                cur.close()
                conn.close()

                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("UPDATE cost SET cost_ev = (%s), cost_house = (%s)" "WHERE start = (%s)", [cost_ev22, cost_house22, start22]);
                conn.commit()
                cur.close()
                conn.close()

            if start23 != None:

                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("UPDATE collecteddata SET consumption = (%s), cost = (%s)" "WHERE start = (%s)", [cons23, cost23, start23]);
                conn.commit()
                cur.close()
                conn.close()
 
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("UPDATE consumption SET consumption_ev = (%s), consumption_house = (%s)" "WHERE start = (%s)", [cons_ev23, cons_house23, start23]);
                conn.commit()
                cur.close()
                conn.close()

                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("UPDATE cost SET cost_ev = (%s), cost_house = (%s)" "WHERE start = (%s)", [cost_ev23, cost_house23, start23]);
                conn.commit()
                cur.close()
                conn.close()

            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("SELECT * FROM collecteddata WHERE date = (%s) ORDER BY start ASC",
                        (chosendate,))
            data1 = cur.fetchall()
            cur.close()
            conn.close()

            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("SELECT * FROM consumption WHERE date = (%s) ORDER BY start ASC",
                        (chosendate,))
            data2 = cur.fetchall()
            cur.close()
            conn.close()

            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("SELECT * FROM cost WHERE date = (%s) ORDER BY start ASC",
                        (chosendate,))
            data3 = cur.fetchall()
            cur.close()
            conn.close()

            #Transforming the lists into dataframes, droping unnecessary colums, transforming strings to floats, merger dataframes, rounding the figures to two decimals and transforming the dataframe to a list
            df_data1 = pd.DataFrame((data1), columns=('date', 'start', 'stop', 'price', 'consumption', 'cost'))
            df_data2 = pd.DataFrame((data2), columns=('date', 'start', 'consumption_house', 'consumption_ev'))
            df_data3 = pd.DataFrame((data3), columns=('date', 'start', 'cost_house', 'cost_ev'))
            df_data2 = df_data2.drop(columns=['date'])
            df_data3 = df_data3.drop(columns=['date'])
            df_data1_2 = pd.merge(df_data1, df_data2, on="start")
            df_data1_3 = pd.merge(df_data1_2, df_data3, on="start")
            df_data1_3[["date2", "time"]] = df_data1_3.start.str.split("T", expand=True)
            df_data1_3[["hour", "min"]] = df_data1_3.time.str.split(":", expand=True)
            df_data1_3 = df_data1_3.drop(columns=['date2', 'time', 'min'])
            data = df_data1_3.values.tolist()

            #Adjusting the dataframe and aggregating the data by date
            df_aggr1 = df_data1_3.drop(columns=['start','stop', 'price'])
            df_aggr1['consumption'] = df_aggr1['consumption'].astype(float)
            df_aggr1['cost'] = df_aggr1['cost'].astype(float)
            df_aggr1['consumption_house'] = df_aggr1['consumption_house'].astype(float)
            df_aggr1['consumption_ev'] = df_aggr1['consumption_ev'].astype(float)
            df_aggr1['cost_house'] = df_aggr1['cost_house'].astype(float)
            df_aggr1['cost_ev'] = df_aggr1['cost_ev'].astype(float)
            df_aggr2 = df_aggr1.groupby(['date'], as_index=False).sum()
            rounded_df_aggr2 = df_aggr2.round(decimals=2)
            aggr = rounded_df_aggr2.values.tolist()

    return render_template("/updateday.html", data=data, chosendate=chosendate, aggr=aggr)  

@app.route("/viewamonth", methods=["GET", "POST"])
def viewamonth():

    if request.method == "GET":

        date_time = datetime.datetime.now()
        chosenmonth = date_time.strftime("%Y-%m")
        monthtoshow=chosenmonth
        chosenmonth = chosenmonth + '%'
    
    if request.method == "POST":
        
        req = request.form
        chosenmonth=req["chosenmonth"]
        monthtoshow=chosenmonth
        chosenmonth = chosenmonth + '%'

    #Getting start times from the consumption table
    starttimes_tup = get_all_starttimes()
    starttimes  = [tupleObj[0] for tupleObj in starttimes_tup]

    #Adjusting the dates and time into year and month
    months = [d[:-9] for d in starttimes]

    #Removing duplicates and sorting
    months_list = list(dict.fromkeys(months))
    months_list.sort()

        #Getting updated data from the database tables
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM collecteddata WHERE date LIKE (%s)",
                (chosenmonth,))
    data1 = cur.fetchall()
    cur.close()
    conn.close()

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM consumption WHERE date LIKE (%s)",
                (chosenmonth,))
    data2 = cur.fetchall()
    cur.close()
    conn.close()

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM cost WHERE date LIKE (%s)",
                (chosenmonth,))
    data3 = cur.fetchall()
    cur.close()
    conn.close()

    #Transforming the lists into dataframes, droping unnecessary colums, transforming strings to floats, merger dataframes, rounding the figures to two decimals and transforming the dataframe to a list
    df_data1 = pd.DataFrame((data1), columns=('date', 'start', 'stop', 'price', 'consumption', 'cost'))
    df_data1['cost'] = df_data1['cost'].astype(float)
    df_data2 = pd.DataFrame((data2), columns=('date', 'start', 'consumption_house', 'consumption_ev'))
    df_data2 = df_data2.drop(columns=['date'])
    df_data3 = pd.DataFrame((data3), columns=('date', 'start', 'cost_house', 'cost_ev'))
    df_data3 = df_data3.drop(columns=['date'])
    df_data1_2 = pd.merge(df_data1, df_data2, on="start")
    df_data1_2_3 = pd.merge(df_data1_2, df_data3, on="start")
    df_data1_2_3b = df_data1_2_3.drop(columns=['start', 'stop', 'price'])
    df_data1_2_3b['consumption'] = df_data1_2_3b['consumption'].astype(float)
    df_data1_2_3b['cost'] = df_data1_2_3b['cost'].astype(float)
    df_data1_2_3b['consumption_house'] = df_data1_2_3b['consumption_house'].astype(float)
    df_data1_2_3b['consumption_ev'] = df_data1_2_3b['consumption_ev'].astype(float)
    df_data1_2_3b['cost_house'] = df_data1_2_3b['cost_house'].astype(float)
    df_data1_2_3b['cost_ev'] = df_data1_2_3b['cost_ev'].astype(float)
    df_aggr2 = df_data1_2_3b.groupby(['date'], as_index=False).sum()

    rounded_df_aggr2 = df_aggr2.round(decimals=3)
    data = rounded_df_aggr2.values.tolist()

    #Adjusting the dataframe and aggregating the data by date
    df_aggr = df_data1_2_3b.drop(columns=['date'])
    df_aggr = df_aggr.agg(['sum'])
    rounded_df_aggr = df_aggr.round(decimals=2)
    aggr = rounded_df_aggr.values.tolist()

    return render_template("/viewamonth.html", months_list=months_list, data=data, monthtoshow=monthtoshow, aggr=aggr)

@app.route("/recalculate")
def recalculate():

    #Getting start times from the consumption table
    starttimes_tup = get_all_starttimes()
    starttimes  = [tupleObj[0] for tupleObj in starttimes_tup]

    #Adjusting the dates and time into year and month
    months = [d[:-9] for d in starttimes]

    #Removing duplicates and sorting
    months_list = list(dict.fromkeys(months))
    months_list.sort()

    return render_template("/recalculate.html", months_list=months_list)

@app.route("/recalculated", methods=["GET", "POST"])
def recalculated():

    if request.method == "POST":

        req = request.form

        action=req["action"]
        chosenmonth=req["chosenmonth"]

        if chosenmonth =="Select month":

            date_time = datetime.datetime.now()
            chosenmonth = date_time.strftime("%Y-%m")

        periodtoshow = chosenmonth
        chosenmonth = chosenmonth + '%'

        #Getting updated data from the database tables
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM collecteddata WHERE date LIKE (%s) ORDER BY start DESC",
                    (chosenmonth,))
        data1 = cur.fetchall()
        cur.close()
        conn.close()

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM consumption WHERE date LIKE (%s) ORDER BY start DESC",
                    (chosenmonth,))
        data2 = cur.fetchall()
        cur.close()
        conn.close()

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM cost WHERE date LIKE (%s) ORDER BY start DESC",
                    (chosenmonth,))
        data3 = cur.fetchall()
        cur.close()
        conn.close()

        if action[0:13] == "Recalculate l":
            periodtoshow = "last 7 days"
            data1 = data1[0:167]
            data2 = data2[0:167]
            data3 = data3[0:167]

        df_data1 = pd.DataFrame((data1), columns=('date', 'start', 'stop', 'price', 'consumption', 'cost'))
        df_data2 = pd.DataFrame((data2), columns=('date', 'start', 'consumption_house', 'consumption_ev'))
        df_data3 = pd.DataFrame((data3), columns=('date', 'start', 'cost_house', 'cost_ev'))

        df_data1 = df_data1.drop(columns=['date'])
        df_data2 = df_data2.drop(columns=['date', 'consumption_house'])
        df_data3 = df_data3.drop(columns=['date', 'cost_house'])
        df_data1_2 = pd.merge(df_data1, df_data2, on="start")
        df_data1_2_3 = pd.merge(df_data1_2, df_data3, on="start")

        df_data1_2_3['cost'] = df_data1_2_3['cost'].astype(float)
        df_data1_2_3['consumption'] = df_data1_2_3['consumption'].astype(float)
        df_data1_2_3['price'] = df_data1_2_3['price'].astype(float)

        df_data1_2_3['consumption_house'] = df_data1_2_3['consumption'] - df_data1_2_3['consumption_ev']
        df_data1_2_3['cost_house'] = df_data1_2_3['consumption_house'] * df_data1_2_3['price']
        df_data1_2_3['cost_ev'] = df_data1_2_3['cost'] - df_data1_2_3['cost_house']

        df_data1_2_3=df_data1_2_3.round(decimals = 3)

        condition = df_data1_2_3['cost_ev'] < 0.0001
        df_data1_2_3.loc[condition,'cost_ev'] = 0

        #Keeping only data that are to be updated, adjusting so that start comes last in the list and transforming it into a tuple list that are to be used when updating the tables
        df_data_til_2 = df_data1_2_3[['start', 'consumption_house', 'consumption_ev']]
        df_data_til_3 = df_data1_2_3[['start', 'cost_house', 'cost_ev']]
        df_data_til_2=df_data_til_2.iloc[:,[1,2,0]]
        df_data_til_3=df_data_til_3.iloc[:,[1,2,0]]
        data_til_2 = list(df_data_til_2.itertuples(index=False, name=None))
        data_til_3 = list(df_data_til_3.itertuples(index=False, name=None))

        #Updating the consumption table
        conn = get_db_connection()
        cur = conn.cursor()
        for d in data_til_2:
            cur.execute("UPDATE consumption set consumption_house = (%s), consumption_ev = (%s) WHERE start = (%s)::text", d)
        conn.commit()
        cur.close()
        conn.close()   

        #Updating the cost table
        conn = get_db_connection()
        cur = conn.cursor()
        for d in data_til_3:
            cur.execute("UPDATE cost set cost_house = (%s), cost_ev = (%s) WHERE start = (%s)::text", d)
        conn.commit()
        cur.close()
        conn.close()

        number_of_hours = len(df_data1_2_3.index)
        number_of_days = round(number_of_hours / 24)

        data=list(df_data1_2_3.itertuples(index=False, name=None))

        return render_template("/recalculated.html" , data=data, number_of_days=number_of_days, number_of_hours=number_of_hours, periodtoshow=periodtoshow)

@app.route("/totalcostmonth", methods=["GET", "POST"])
def totalcostmonth():

    if request.method == "GET":

        date_time = datetime.datetime.now()
        costmonth = date_time.strftime("%Y-%m")
        monthtoshow=costmonth
        costmonth = costmonth + '%'

    if request.method == "POST":
            
        req = request.form   #Lagrer i variablen req data som request lager en fin diconary av
        costmonth=req["costmonth"]
        monthtoshow=costmonth
        costmonth = costmonth + '%'

    fixedmontlycost=session.get("fixedmontlycost")
    fixedkwhcost=session.get("fixedkwhcost")    

    #Flashing message if necessary data is not input
    if fixedmontlycost == None and fixedkwhcost == None:
        flash("You have to first input fixed cost to get total costs a given month!")
        return redirect("/setup")

    #Getting start times from the consumption table
    starttimes_tup = get_all_starttimes()
    starttimes  = [tupleObj[0] for tupleObj in starttimes_tup]

    #Adjusting from date and time to only year and month
    months = [d[:-9] for d in starttimes]

    #Removing duplicates and sorting
    months_list = list(dict.fromkeys(months))
    months_list.sort()

    #Henter oppdatert data fra databasetabellene
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM collecteddata WHERE date LIKE (%s)",
                (costmonth,))
    data1 = cur.fetchall()
    cur.close()
    conn.close()

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM consumption WHERE date LIKE (%s)",
                (costmonth,))
    data2 = cur.fetchall()
    cur.close()
    conn.close()

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM cost WHERE date LIKE (%s)",
                (costmonth,))
    data3 = cur.fetchall()
    cur.close()
    conn.close()

    #Transforming the lists into dataframes, droping unnecessary colums, transforming strings to floats, merger dataframes, rounding the figures to two decimals and transforming the dataframe to a list
    df_data1 = pd.DataFrame((data1), columns=('date', 'start', 'stop', 'price', 'consumption', 'cost'))
    df_data1['cost'] = df_data1['cost'].astype(float)
    df_data2 = pd.DataFrame((data2), columns=('date', 'start', 'consumption_house', 'consumption_ev'))
    df_data2 = df_data2.drop(columns=['date'])
    df_data3 = pd.DataFrame((data3), columns=('date', 'start', 'cost_house', 'cost_ev'))
    df_data3 = df_data3.drop(columns=['date'])
    df_data1_2 = pd.merge(df_data1, df_data2, on="start")
    df_data1_2_3 = pd.merge(df_data1_2, df_data3, on="start")
    df_data1_2_3b = df_data1_2_3.drop(columns=['start', 'stop', 'price'])
    df_data1_2_3b['consumption'] = df_data1_2_3b['consumption'].astype(float)
    df_data1_2_3b['cost'] = df_data1_2_3b['cost'].astype(float)
    df_data1_2_3b['consumption_house'] = df_data1_2_3b['consumption_house'].astype(float)
    df_data1_2_3b['consumption_ev'] = df_data1_2_3b['consumption_ev'].astype(float)
    df_data1_2_3b['cost_house'] = df_data1_2_3b['cost_house'].astype(float)
    df_data1_2_3b['cost_ev'] = df_data1_2_3b['cost_ev'].astype(float)

    #Adjusting the dataframe and aggregating data by date
    df_aggr = df_data1_2_3b.drop(columns=['date'])
    df_aggr = df_aggr.agg(['sum'])
    rounded_df_aggr = df_aggr.round(decimals=2)
    aggr = rounded_df_aggr.values.tolist()

    #Calculating various cost elements
    cost_house_ellevio = round((float(aggr[0][2]) * float(fixedkwhcost)) + float(fixedmontlycost), 2)
    cost_ev_ellevio = round((float(aggr[0][3]) * float(fixedkwhcost)), 2)
    total_cost_ellevio = round(cost_house_ellevio + cost_ev_ellevio, 2)
    
    total_cost = round(aggr[0][1] + total_cost_ellevio, 2)
    total_cost_tibber_per_kwh = round(aggr[0][1]/aggr[0][0], 2)
    total_cost_per_kwh = round(total_cost/aggr[0][0], 2)

    if aggr[0][3] != 0:
        cost_ev_total = round(aggr[0][5] + cost_ev_ellevio, 2)
        ev_cost_tibber_per_kwh = round(aggr[0][5] / aggr[0][3], 2) 
        cost_ev_per_kwh_total = round(cost_ev_total / aggr[0][3], 2)
    else:
        cost_ev_total = 0
        ev_cost_tibber_per_kwh = 0
        cost_ev_per_kwh_total = 0

    cost_house_total = round(aggr[0][4] + cost_house_ellevio, 2)
    house_cost_tibber_per_kwh = round(aggr[0][4] / aggr[0][2], 2)
    cost_house_per_kwh_total = round(cost_house_total / aggr[0][2], 2)

    return render_template("/totalcostmonth.html", months_list=months_list, aggr=aggr, cost_house_ellevio=cost_house_ellevio, cost_ev_ellevio=cost_ev_ellevio, total_cost_ellevio=total_cost_ellevio, monthtoshow=monthtoshow, total_cost = total_cost, total_cost_tibber_per_kwh = total_cost_tibber_per_kwh, total_cost_per_kwh = total_cost_per_kwh, cost_ev_total = cost_ev_total, ev_cost_tibber_per_kwh = ev_cost_tibber_per_kwh, cost_ev_per_kwh_total = cost_ev_per_kwh_total, cost_house_total = cost_house_total, house_cost_tibber_per_kwh = house_cost_tibber_per_kwh, cost_house_per_kwh_total = cost_house_per_kwh_total)


@app.route("/viewconsumption", methods=["GET", "POST"])
def viewconsumption():

    if request.method == "GET":

        return render_template("viewconsumption.html")

    if request.method == "POST":

        req = request.form 
        action = req.get("action")

        if action[10:12] == "24":
            hourstocollect = 24
        
        if action[10:12] == "48":
            hourstocollect = 48

        if action[10:12] == "72":
            hourstocollect = 72
         
        ###############################################################################################
        #Collecting data from Tibber and saving it in lists that are merged and made into a tuple list
        ###############################################################################################
        account=tibber.Account(tibber_token)
        home = account.homes[0]
        hour_data = home.fetch_consumption("HOURLY", last=hourstocollect)
       
        start=[]
        stop=[]
        price=[]
        cons=[]
        cost=[]

        for hour in hour_data:
            data1=(hour.from_time)
            data2=(hour.to_time)
            data3=(f"{hour.unit_price}{hour.currency}")
            data4=(hour.consumption)
            data5=(hour.cost)
            start.append(data1)
            stop.append(data2)
            price.append(data3)
            cons.append(data4)
            cost.append(data5)        

        #Removing unnecessary info from the date variable
        start = [d[:-13] for d in start]
        stop = [d[:-13] for d in stop]

        #Removing SEK from the list containing prices
        price = ([s.replace('SEK', '') for s in price])

        #Merging all lists of data to one tuple list and transforming it into a dataframe
        def merge(stop,price,cons,cost,start):
            merged_list = [(stop[i], price[i], cons[i], cost[i],start[i]) for i in range(0, len(start))]
            return merged_list
        data = merge(stop,price,cons,cost,start)

    return render_template("/viewconsumption.html", data=data, hourstocollect=hourstocollect)


@app.route("/viewprices", methods=["GET", "POST"])
def viewprices():

    if request.method == "GET":

        account=tibber.Account(tibber_token)
        home = account.homes[0]
        current_subscription = home.current_subscription
        #price_info = current_subscription.price_info
        price_now = current_subscription.price_info.current.total
        #price_nordpool = current_subscription.price_info.current.energy
        price_level = current_subscription.price_info.current.level
        price_info_today = current_subscription.price_info.today
        price_info_tomorrow = current_subscription.price_info.tomorrow
      
        ##############################
        # Collecting tomorrow's prices
        ##############################

        total_td=[]
        energy_td=[]
        tax_td=[]
        starts_at_td=[]
        currency_td=[]
        level_td=[]

        for hour in price_info_today:
            data1=(hour.total)
            data2=(hour.energy)
            data3=(hour.tax)
            data4=(hour.starts_at)
            data5=(hour.currency)
            data6=(hour.level)   

            total_td.append(data1)
            energy_td.append(data2)
            tax_td.append(data3)
            starts_at_td.append(data4)
            currency_td.append(data5)
            level_td.append(data6)

        #Removing unnecessary info from the date variable
        starts_at_td = [d[11:-13] for d in starts_at_td]

        #Merging all lists of data to one tuple list
        def merge(total_td,energy_td,tax_td,starts_at_td,currency_td,level_td):
            merged_list = [(total_td[i], energy_td[i], tax_td[i], starts_at_td[i],currency_td[i],level_td[i]) for i in range(0, len(total_td))]
            return merged_list
        prices_today = merge(total_td,energy_td,tax_td,starts_at_td,currency_td,level_td)

        ##############################
        # Collecting today's prices
        ##############################

        total_tm=[]
        energy_tm=[]
        tax_tm=[]
        starts_at_tm=[]
        currency_tm=[]
        level_tm=[]

        for hour in price_info_tomorrow:
            data1=(hour.total)
            data2=(hour.energy)
            data3=(hour.tax)
            data4=(hour.starts_at)
            data5=(hour.currency)
            data6=(hour.level)   

            total_tm.append(data1)
            energy_tm.append(data2)
            tax_tm.append(data3)
            starts_at_tm.append(data4)
            currency_tm.append(data5)
            level_tm.append(data6)

        #Merging all lists of data to one tuple list
        def merge(total_tm,energy_tm,tax_tm,starts_at_tm,currency_tm,level_tm):
            merged_list = [(total_tm[i], energy_tm[i], tax_tm[i], starts_at_tm[i],currency_tm[i],level_tm[i]) for i in range(0, len(total_tm))]
            return merged_list
        prices_tomorrow = merge(total_tm,energy_tm,tax_tm,starts_at_tm,currency_tm,level_tm)

    return render_template("/viewprices.html", prices_today=prices_today, prices_tomorrow=prices_tomorrow, price_now=price_now, price_level = price_level)



@app.errorhandler(500)
def internal_server_error(e):
    return render_template('500.html'), 500

@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404

@app.errorhandler(403)
def forbidden(e):
    return render_template('403.html'), 403