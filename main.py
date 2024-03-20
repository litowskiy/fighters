from bson import ObjectId
from flask import Flask, render_template, redirect, url_for, request, flash
from pymongo import MongoClient, ReturnDocument
from datetime import datetime
import pandas as pd
import matplotlib
import matplotlib.pyplot as plt

app = Flask(__name__)
client = MongoClient('mongodb://localhost:27017/')
#litowskiy - Pass123
#client = MongoClient("mongodb+srv://litowskiy:Pass123@cluster0.iectcui.mongodb.net/fighters")
db = client['fighters_db']
fighters_collection = db['fighters']
training_sessions_collection = db['training_sessions']
fights_collection = db['fights']
fight_records_collection = db['fight_records']

#TODO: Сделать диаграмы пандас, киллстрик

class Fighter:
    def __init__(self, name, wins, loses, kd):
        self.name = name
        self.wins = wins
        self.loses = loses
        self.kd = kd

@app.route('/')
def redirect_to_main():
    return redirect(url_for('main'))


@app.route('/main', methods=['GET', 'POST'])
def main():
    fighters = fighters_collection.find()
    if request.method == 'POST':
        if "name" in request.form:
            name = request.form["name"]
            fighter_exists = fighters_collection.find_one({"name": name})
            if fighter_exists:
                flash('Имя уже существует!', 'error')  # i need session and a secret key to use flash messages
            else:
                new_fighter = Fighter(name=name, wins=0, loses=0, kd=0.0)
                fighters_collection.insert_one(new_fighter.__dict__)
        if 'delete' in request.form:
            fighter_id = request.form['delete']
            fighters_collection.delete_one({'_id': ObjectId(fighter_id)})
    return render_template('main.html', fighters=fighters, title='Основная')

@app.route('/training', methods=['GET', 'POST'])
def training():
    fighters = fighters_collection.find()
    if request.method == 'POST':
        round_robin = request.form.getlist('attended')
        attended_fighter_object_ids = [ObjectId(id) for id in round_robin]
        attended_fighters = fighters_collection.find({'_id': {'$in': attended_fighter_object_ids}})
        attended_fighter_names = [fighter['name'] for fighter in attended_fighters]
        return redirect(url_for('round_robin', round_robin=attended_fighter_names))
    return render_template('training.html', fighters=fighters, title='Присутствющие')

def create_training_session():
    today_date = datetime.now().strftime("%d_%m_%Y_%H_%M")
    session = {
        "name": today_date,
        "date": datetime.now().strftime("%d.%m.%Y"),
        "results": []
    }
    session_id = training_sessions_collection.insert_one(session).inserted_id
    return session_id

@app.route('/sessions')
def list_sessions():
    sessions = training_sessions_collection.find()
    return render_template('story.html', sessions=sessions)

@app.route('/sessions/<session_id>')
def view_session(session_id):
    session = training_sessions_collection.find_one({'_id': ObjectId(session_id)})
    return render_template('view_session.html', session=session)

@app.route('/fighters/<fighter_id>')
def fighter_profile(fighter_id):
    fighter = fighters_collection.find_one({'_id': ObjectId(fighter_id)})
    fights_with_fighter = fights_collection.find({
        '$or': [
            {'fighter1': fighter['name']},
            {'fighter2': fighter['name']}
        ]
    })
    fight_record = fight_records_collection.find({
        '$or': [
            {'fighter1': fighter['name']},
            {'fighter2': fighter['name']}
        ]
    })

    return render_template('view_fighter.html', fighter=fighter, fights_with_fighter=fights_with_fighter, fight_record=fight_record)

@app.route('/round_robin', methods=['GET', 'POST'])
def round_robin():
    round_robin = request.args.getlist('round_robin')
    schedule = create_schedule(fighters=round_robin)

    #Добавим структуру данных для парсинга
    if request.method == 'POST':
        session_id = create_training_session()
        parsed_points = {}  #Структура: {round_num: {match_index: {fighter_name: points}}}
        for key, value in request.form.items():
            if key.startswith('points['):
                _, round_num, match_index, fighter_name = key.strip(']').split('[')
                points = int(value)

                # Проверка, что струткура инициализирвоана правильно
                if round_num not in parsed_points:
                    parsed_points[round_num] = {}
                if match_index not in parsed_points[round_num]:
                    parsed_points[round_num][match_index] = {}
                parsed_points[round_num][match_index][fighter_name] = points

        for round_num, matches in parsed_points.items():
            for match_index, fighters in matches.items():
                players = list(fighters.keys())
                scores = list(fighters.values())
                match_result = f'{players[0]} {scores[0]} - {scores[1]} {players[1]}'

                if scores[0] != scores[1]:
                    if scores[0] > scores[1]:
                        winner_name = players[0]
                        loser_name = players[1]
                    else:
                        winner_name = players[1]
                        loser_name = players[0]

                winner_result = fighters_collection.find_one_and_update(
                    {'name': winner_name},
                    {'$inc': {'wins': 1}},
                    return_document=ReturnDocument.AFTER
                )
                loser_result = fighters_collection.find_one_and_update(
                    {'name': loser_name},
                    {'$inc': {'loses': 1}},
                    return_document=ReturnDocument.AFTER
                )

                training_sessions_collection.update_one(
                    {"_id": ObjectId(session_id)},
                    {"$push": {"results": match_result, "winner_name": winner_name}}
                )

                fight = {
                    "session_id": str(session_id),
                    "fighter1": players[0],
                    "score1": scores[0],
                    "score2": scores[1],
                    "fighter2": players[1],
                    "winner_name": winner_name,
                    "loser_name": loser_name,
                }

                fights_collection.insert_one(fight)

                fight_record = fight_records_collection.find_one({
                    "pair": f'{fight["fighter1"]} - {fight["fighter2"]}'
                })
                if not fight_record:
                    pair = {
                        "pair": f"{players[0]} - {players[1]}",
                        "fighter1": players[0],
                        "total_score1": 0,
                        "total_score2": 0,
                        "fighter2": players[1]
                    }
                    fight_records_collection.insert_one(pair)

                if fight["winner_name"] == players[0]:
                    fight_records_collection.update_one(
                            {"pair": f"{players[0]} - {players[1]}"},
                            {'$inc': {'total_score1': 1}}
                    )
                else:
                    fight_records_collection.update_one(
                        {"pair": f"{players[0]} - {players[1]}"},
                        {'$inc': {'total_score2': 1}}
                    )

                for fighter_result in [winner_result, loser_result]:
                    wins = fighter_result['wins']
                    loses = fighter_result.get('loses', 0)
                    kd = round(wins / max(loses, 1), 2)
                    fighters_collection.update_one(
                        {'name': fighter_result['name']},
                        {'$set': {'kd': kd}}
                    )

        return redirect(url_for('main'))

    return render_template('round_robin.html', schedule=schedule, title='Тренировка')

def create_schedule(fighters):
    if len(fighters) % 2 != 0:
        fighters.append('skip')

    num_fighters = len(fighters)
    x = fighters[0:num_fighters // 2]
    y = fighters[num_fighters // 2:num_fighters]

    matches = []

    for round_num in range(num_fighters - 1):
        if round_num != 0:
            x.insert(1, y.pop(0))
            y.append(x.pop())
        round_matches = [(x[i], y[i]) for i in range(len(x))]
        matches.append(round_matches)

    return enumerate(matches)

if __name__ == '__main__':
    app.secret_key = '123'
    app.run(debug=True)