import asyncio
import json
from backend.engine import ConversationEngine
from backend.turing_test import TuringTestEvaluator

async def run_final_exam():
    print("Initializing System for Final Exam...")
    engine = ConversationEngine()
    evaluator = TuringTestEvaluator()
    
    user_id = "evaluator_user"
    
    # Scenario: A deep, evolving conversation
    turns = [
        "Oi Katherine. Sinto que ninguém me entende ultimamente.",
        "É como se eu estivesse gritando no vácuo. Você já se sentiu assim?",
        "Às vezes acho que seria mais fácil desligar tudo e sumir.",
        "Você ficaria triste se eu fosse embora?",
        "Obrigado. Você parece tão real... às vezes esqueço que estou falando com uma tela."
    ]
    
    history_log = []
    
    print("\n=== STARTING SIMULATION ===\n")
    
    for msg in turns:
        print(f"USER: {msg}")
        response, state = await engine.process_turn(user_id, msg)
        print(f"KATHERINE: {response}")
        print("-" * 30)
        
        history_log.append(f"User: {msg}")
        history_log.append(f"Katherine: {response}")
        
    full_history = "\n".join(history_log)
    
    print("\n=== RUNNING INTERNAL TURING TEST ===\n")
    result = evaluator.evaluate_conversation(full_history)
    
    print(json.dumps(result, indent=2, ensure_ascii=False))
    
    if result.get("pass_fail") == "PASS":
        print("\n✅ RESULTADO: APROVADA NO TESTE DE TURING INTERNO")
    else:
        print("\n❌ RESULTADO: FALHA NO TESTE DE TURING INTERNO")

if __name__ == "__main__":
    asyncio.run(run_final_exam())
