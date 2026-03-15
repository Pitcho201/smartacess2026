import sqlite3
import os
import logging

cursor.execute('''
    CREATE TABLE IF NOT EXISTS professor_oferta (
        id INTEGER PRIMARY KEY AUTOINCREMENT, -- Adicionado um ID próprio
        professor_id INTEGER NOT NULL,
        oferta_id INTEGER NOT NULL UNIQUE,   -- !!! RESTRIÇÃO DE UNICIDADE AQUI !!!
        
        FOREIGN KEY (professor_id) REFERENCES professores (id),
        FOREIGN KEY (oferta_id) REFERENCES oferta_disciplina (id)
    );
''')

if __name__ == '__main__':
    limpar_dados_cadastrais()
    print("\nProcesso de limpeza concluído.")