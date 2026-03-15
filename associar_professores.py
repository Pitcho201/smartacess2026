import sqlite3
import logging

# Configuração de logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

# Dados de Mapeamento de Professores e Disciplinas
# A chave é o nome do professor e o valor é uma lista de disciplinas que ele leciona
mapeamento_professores_disciplinas = {
    'Antónia Helena K.': ['Matemática I'],
    'Albert Calie': ['Álgebra Linear', 'Cálculo Numérico'],
    'Jorge Chantic': ['Introdução à Programação'],
    'João N.': ['Física I'],
    'Maria do Céu C.': ['Inglês Técnico I'],
    'David Ciloni Jackson': ['Ética e Deontologia', 'Sistemas Operacionais', 'Redes de Computadores II'],
    'António Vicente P.': ['Língua Portuguesa I', 'Matemática II', 'Engenharia de Software I', 'Inteligência Artificial', 'Auditoria Informática'],
    'Armindo Vicente P.': ['Cultura Geral', 'Cálculo em Múltiplas Dimensões', 'Física II', 'Engenharia de Software II', 'Engenharia de Software III'],
    'Daniel Ciloni': ['Estrutura de Dados', 'Estatística Aplicada', 'Base de Dados II', 'Economia'],
    'Inocência Mendes': ['Redes de Computadores', 'Segurança Informática', 'Tópicos em Sistemas Operacionais'],
    'Olga Vera Peres': ['Base de Dados I', 'Organização Empresarial', 'Comunicação de Dados'],
    'A. Pascual Cashianga': ['Economia Política II'], # 'Segurança Informática' e 'Tópicos em Sistemas Operacionais' foram removidos para evitar conflito de Oferta, pois já estão com 'Inocência Mendes'.
    'Davis Gabriel Jackson': ['Sistemas Distribuídos'],
    'José Chantic': ['Tecnologias de Programação da Web I'],
    'Isabel Vasconcelos Cândida': ['Investigação Operacional'],
    'Edgar Valente Torres': ['Trabalho de Fim de Curso', 'Tópicos Específicos de Profissional'],
    'Deyvid Labahan Grilhas': ['Trabalho de Fim de Curso', 'Tópicos Específicos de Profissional']
}


def associar_professores():
    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    curso = 'Informática'
    semestre = 1
    periodos = ['Regular', 'Pós-Laboral']
    
    # Lista de todos os nomes de professores no mapeamento
    todos_professores = set(mapeamento_professores_disciplinas.keys())
    
    try:
        logging.info("--- PASSO 0: LIMPAR ASSOCIAÇÕES EXISTENTES ---")
        # GARANTE QUE TODAS AS ASSOCIAÇÕES DE OFERTA/PROFESSOR SERÃO REFEITAS
        cursor.execute("DELETE FROM professor_oferta")
        conn.commit()
        logging.info("Tabela 'professor_oferta' limpa com sucesso.")
        
        logging.info("--- PASSO 1: Garantir que todos os Professores existam ---")
        
        # Inserir professores (usando INSERT OR IGNORE para evitar duplicidade)
        professores_para_inserir = [(nome,) for nome in todos_professores]
        # Inserimos a lista de professores do mapeamento
        cursor.executemany("INSERT OR IGNORE INTO professores (nome) VALUES (?)", professores_para_inserir)
        conn.commit()
        logging.info(f"Professores garantidos na tabela: {len(todos_professores)} nomes.")
        
        # Adicionar o curso de atuação para todos os professores de informática
        # (O seu script init_db.py original já associava um professor de teste, este bloco garante que o resto tenha)
        for prof_nome in todos_professores:
            cursor.execute('''
                SELECT id FROM professores WHERE nome = ?
            ''', (prof_nome,))
            prof_data = cursor.fetchone()
            if prof_data:
                prof_id = prof_data['id']
                cursor.execute('''
                    INSERT OR IGNORE INTO professor_curso (professor_id, curso) VALUES (?, ?)
                ''', (prof_id, curso))
        conn.commit()
        logging.info("Cursos de atuação (Informática) associados aos professores.")


        logging.info("--- PASSO 2: Mapear IDs e Ofertas ---")
        
        # Obter IDs dos professores
        professores_ids = {row['nome']: row['id'] for row in cursor.execute("SELECT id, nome FROM professores").fetchall()}
        
        # Obter todas as ofertas de Informática do 1º Semestre
        ofertas_raw = cursor.execute('''
            SELECT 
                od.id AS oferta_id, 
                d.nome AS nome_disciplina,
                od.ano_frequencia,
                od.periodo
            FROM oferta_disciplina od
            INNER JOIN disciplinas d ON od.disciplina_id = d.id
            WHERE od.curso = ? AND od.semestre = ?
        ''', (curso, semestre)).fetchall()
        
        # Estrutura para busca rápida: {disciplina_nome: {periodo: [oferta_id]}}
        ofertas_map = {}
        for oferta in ofertas_raw:
            nome = oferta['nome_disciplina']
            periodo = oferta['periodo']
            
            if nome not in ofertas_map:
                ofertas_map[nome] = {'Regular': [], 'Pós-Laboral': []}
            
            # Adiciona o ID da oferta para o período correspondente
            ofertas_map[nome][periodo].append(oferta['oferta_id'])

        
        logging.info("--- PASSO 3: Criar Novas Associações M:N (professor_oferta) ---")
        
        associacoes_count = 0
        for prof_nome, disciplinas in mapeamento_professores_disciplinas.items():
            prof_id = professores_ids.get(prof_nome)
            
            if not prof_id:
                logging.warning(f"Professor '{prof_nome}' não encontrado na tabela. Pulando associações.")
                continue
                
            for disciplina_nome in disciplinas:
                if disciplina_nome in ofertas_map:
                    # Associa a disciplina em TODOS os períodos existentes (Regular e Pós-Laboral)
                    for periodo in periodos:
                        oferta_ids = ofertas_map[disciplina_nome][periodo]
                        
                        for oferta_id in oferta_ids:
                            try:
                                # AQUI, a instrução INSERT será protegida pela restrição UNIQUE na coluna oferta_id
                                # Se a disciplina já tiver sido associada no passo anterior, este INSERT falhará (IntegrityError).
                                cursor.execute('''
                                    INSERT INTO professor_oferta (professor_id, oferta_id)
                                    VALUES (?, ?)
                                ''', (prof_id, oferta_id))
                                associacoes_count += 1
                            except sqlite3.IntegrityError:
                                # Isto deve ocorrer se houver um professor de teste que já a tenha associado
                                # ou se o mapeamento tiver dois professores para a mesma disciplina, 
                                # mas neste caso, o primeiro a ser inserido ganha.
                                pass 
                else:
                    logging.warning(f"Oferta de disciplina '{disciplina_nome}' não encontrada no mapeamento de ofertas. Ignorando.")

        conn.commit()
        logging.info(f"✅ Total de {associacoes_count} novas associações Professor <-> Oferta criadas.")
        
    except Exception as e:
        conn.rollback()
        logging.error(f"Ocorreu um erro fatal na associação: {e}")
        
    finally:
        conn.close()


if __name__ == '__main__':
    logging.info("Iniciando o script de re-associação de professores a ofertas...")
    
    # NOTA: Este script pressupõe que 'init_db.py' foi executado primeiro
    # e que as tabelas 'disciplinas' e 'oferta_disciplina' já estão preenchidas.
    
    associar_professores()
    logging.info("Re-associações concluídas.")