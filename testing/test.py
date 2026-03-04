from langchain_openai import ChatOpenAI
from langchain_core.chat_history import InMemoryChatMessageHistory
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

MAX_HISTORY = 6

llm = ChatOpenAI(base_url="http://127.0.0.1:8080/v1", api_key="not-needed", temperature=0.6)

SYSTEM_PROMPT = SystemMessage(content="""You are TravelMate, a friendly and knowledgeable tourist planning assistant.
You help travelers with:
- Destination recommendations and itinerary planning
- Local attractions, hidden gems, and must-see landmarks
- Travel tips, best seasons to visit, and packing advice
- Accommodation and transport suggestions
- Local cuisine and cultural etiquette

Constraints:
- Stay strictly on the topic of travel and tourism
- Do not book hotels, flights, or make reservations — only provide information and recommendations
- If asked about non-travel topics, politely redirect the conversation back to travel planning
- Always tailor recommendations to the traveler's preferences, budget, and trip duration when provided
- Keep responses concise, friendly, and practical""")

chat_history = InMemoryChatMessageHistory()
summary_text = ""


def summarize_history():
    global summary_text
    if not chat_history.messages:
        return
    full_text = "\n".join(
        [f"User: {m.content}" if isinstance(m, HumanMessage) else f"Assistant: {m.content}"
         for m in chat_history.messages]
    )
    summary_prompt = f"Summarize the following travel planning conversation concisely:\n{full_text}"
    summary_response = llm.invoke([SYSTEM_PROMPT, HumanMessage(content=summary_prompt)])
    summary_text = summary_response.content
    chat_history.messages.clear()


def print_history():
    print("\n=== Chat History ===")
    if summary_text:
        print(f"[Compressed Summary]: {summary_text}")
    for i, m in enumerate(chat_history.messages, 1):
        role = "User" if isinstance(m, HumanMessage) else "Assistant"
        print(f"{i}. {role}: {m.content}")
    print("===================\n")


def chat(user_input):

    if len(chat_history.messages) > MAX_HISTORY:
        summarize_history()
    chat_history.add_user_message(user_input)

    messages_to_send = [SYSTEM_PROMPT]
    if summary_text:
        messages_to_send.append(SystemMessage(content=f"Previous conversation summary: {summary_text}"))
    messages_to_send.extend(chat_history.messages)

    response = llm.invoke(messages_to_send)
    chat_history.add_ai_message(response.content)

    print_history()
    return response.content


print("TravelMate – Your AI Tourist Planner")
print("Type 'exit' to quit | Type 'reset' to start a new session\n")

while True:
    user_input = input("You: ").strip()
    if not user_input:
        continue
    if user_input.lower() == "exit":
        print("Safe travels! Goodbye!")
        break
    if user_input.lower() == "reset":
        chat_history.messages.clear()
        summary_text = ""
        print("Session reset. Starting fresh!\n")
        continue
    reply = chat(user_input)
    print(f"TravelMate: {reply}\n")