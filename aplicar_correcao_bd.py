import sqlite3
import logging

# Configuração de logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

def aplicar_correcao_professor_oferta():
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    
    try:
        logging.info("Iniciando a correção da tabela 'professor_oferta'...")
        
        # 1. Renomear a tabela antiga (Backup temporário)
        cursor.execute("ALTER TABLE professor_oferta RENAME TO professor_oferta_old;")
        logging.info("Tabela 'professor_oferta' renomeada para 'professor_oferta_old'.")
        
        # 2. Criar a nova tabela com a restrição UNIQUE em oferta_id
        # Note que a versão antiga não tinha a coluna 'id' para PRIMARY KEY, 
        # mas como estamos recriando, vamos usá-lo para uma PK correta.
        cursor.execute('''
            CREATE TABLE professor_oferta (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                professor_id INTEGER NOT NULL,
                oferta_id INTEGER NOT NULL UNIQUE,
                
                FOREIGN KEY (professor_id) REFERENCES professores (id),
                FOREIGN KEY (oferta_id) REFERENCES oferta_disciplina (id)
            );
        ''')
        logging.info("Nova tabela 'professor_oferta' criada com a restrição UNIQUE em 'oferta_id'.")
        
        # 3. Migrar os dados antigos (Se existirem, ignorando o campo 'id' que não existia antes)
        # Atenção: Se a sua tabela antiga violava a regra (oferta associada a 2+ profs), 
        # esta migração falharia devido ao UNIQUE constraint.
        # Por isso, é melhor REFAZER as associações com o script 'associar_professores.py'.
        
        # 4. Excluir a tabela antiga para limpeza (opcional, dependendo da necessidade de backup)
        cursor.execute("DROP TABLE professor_oferta_old;")
        logging.info("Tabela temporária excluída.")

        conn.commit()
        logging.info("✅ Correção da estrutura da tabela concluída com sucesso!")
        
    except sqlite3.OperationalError as e:
        if "no such table" in str(e) or "already exists" in str(e):
             logging.warning(f"Erro Operacional (Ignorado): {e}. A tabela pode não existir ou a correção já foi aplicada. Tentando garantir que está correta...")
             
             # Tenta garantir a exclusão da versão antiga, caso a primeira etapa falhe.
             cursor.execute("DROP TABLE IF EXISTS professor_oferta;")
             cursor.execute('''
                 CREATE TABLE IF NOT EXISTS professor_oferta (
                     id INTEGER PRIMARY KEY AUTOINCREMENT,
                     professor_id INTEGER NOT NULL,
                     oferta_id INTEGER NOT NULL UNIQUE,
                     
                     FOREIGN KEY (professor_id) REFERENCES professores (id),
                     FOREIGN KEY (oferta_id) REFERENCES oferta_disciplina (id)
                 );
             ''')
             conn.commit()
             logging.info("✅ Tabela 'professor_oferta' garantida com o esquema correto.")

        else:
            logging.error(f"Erro ao aplicar correção: {e}")
            conn.rollback()
            
    except Exception as e:
        logging.error(f"Erro inesperado: {e}")
        conn.rollback()
        
    finally:
        conn.close()

if __name__ == '__main__':
    aplicar_correcao_professor_oferta()

    # *************************************************************************
    # IMPORTANTE: APÓS EXECUTAR ESTE SCRIPT, EXECUTE O SCRIPT 
    # 'associar_professores.py' (AQUELE QUE TE FORNECEI COM A LIMPEZA) 
    # PARA REPOPULAR AS ASSOCIAÇÕES CONFORME AS NOVAS REGRAS DE UNICIDADE.
    # *************************************************************************