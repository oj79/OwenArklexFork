import random
import requests
import copy
from typing import List, Dict, Any, Tuple, Optional, Union
from arklex.evaluation.get_documents import load_docs
from arklex.evaluation.chatgpt_utils import chatgpt_chatbot
from arklex.env.env import Env
from arklex.orchestrator.NLU.nlu import SlotFilling
from arklex.env.tools.tools import Tool
from arklex.utils.utils import truncate_string

MAX_DOC_SNIPPET: int = 1000

ATTR_TO_PROFILE: str = "Convert the following list user attributes in to a text description of a customer profile for the following company:\n{company_summary}\nThe user attributes are here:\n{user_attr}"
ADAPT_GOAL: str = "Assume you are planning to speak to a chatbot with the following goal in mind:\n{goal}\nUsing the company information below, re-write this goal into one that is more specific to the company and align with your profile. The new goal should be more specific either relevent to your profile or the company's details. Here is a summary of the company:\n{company_summary}\n{doc}\n{user_profile}"
ADD_ATTRIBUTES: str = "Your job is to add attributes to a customer profile. Here is an example of an existing profile with the categories on the left and the attributes on the right:\n{user_profile}\nSuggest three attributes for the following category:\n{category}\nThese attributes should be specific values that are relevant to the category and apply to potential customers of the company. You should return a comma separated list of attributes without any descriptions of the attributes. Generated the attributes based on a summary of the company and the company webpage and what kind of customers the compnay is likely targeting. Here is the summary fo the company:\n{company_summary}\nHere is the webpage:\n{company_doc}"
ADD_ATTRIBUTES_WO_DOC: str = "Your job is to add attributes to a customer profile. Here is an example of an existing profile with the categories on the left and the attributes on the right:\n{user_profile}\nSuggest three attributes for the following category:\n{category}\nThese attributes should be specific values that are relevant to the category and apply to potential customers of the company. You should return a comma separated list of attributes without any descriptions of the attributes. Generated the attributes based on a summary of the company and what kind of customers the compnay is likely targeting. Here is the summary fo the company:\n{company_summary}"


def build_profile(
    synthetic_data_params: Dict[str, Any], config: Dict[str, Any]
) -> Tuple[
    List[str],
    List[str],
    List[Dict[str, Any]],
    List[Dict[str, Any]],
    List[Dict[str, Any]],
]:
    labels_list: List[Dict[str, Any]] = []
    attributes_list: List[Dict[str, Any]] = []
    system_attributes_list: List[Dict[str, Any]] = []
    documents: List[Dict[str, str]] = load_docs(
        config["documents_dir"], config, synthetic_data_params["num_goals"] * 2
    )
    predefined_attributes: Dict[str, Dict[str, Any]] = filter_attributes(config)
    augmented_attributes: Dict[str, List[str]] = augment_attributes(
        predefined_attributes, config, documents
    )

    if not config[
        "custom_profile"
    ]:  # Use predefined profiles (from user_attributes.json)
        user_profile: Dict[str, Any] = {}
        for i in range(synthetic_data_params["num_convos"]):
            strategy: str = "react"
            attributes, matched_attribute_to_goal = pick_attributes(
                user_profile,
                augmented_attributes,
                config["user_attributes"]["goal"]["values"],
                strategy=strategy,
                client=config["client"],
            )
            doc_content: str = random.choice(documents)["content"] if documents else ""
            doc_snippet: str = truncate_string(doc_content, MAX_DOC_SNIPPET)
            doc: str = (
                "Here is a page from the company website: "
                # + random.choice(documents)["content"]
                + doc_snippet
                if documents
                else ""
            )
            user_profile_str: str = "Here is the your profile: " + "; ".join(
                f"{key}: {value}" for key, value in attributes.items()
            )
            goal: str = adapt_goal(
                goal=attributes["goal"],
                config=config,
                doc=doc,
                user_profile=user_profile_str,
            )
            attributes["goal"] = goal
            labels_list.append(matched_attribute_to_goal)
            attributes_list.append(attributes)
        if config["system_inputs"]:
            system_attributes_list = select_system_attributes(
                config, synthetic_data_params
            )
        else:
            system_attributes_list = [{}] * synthetic_data_params["num_convos"]

    else:  # Use custom profiles (from database)
        user_profiles, system_attributes = get_custom_profiles(config)
        for i in range(synthetic_data_params["num_convos"]):
            system_attribute: Dict[str, Any] = {}
            user_profile: Dict[str, Any] = {}
            binding_index: Dict[str, int] = {}
            for key, value in config["user_attributes"]["system_attributes"].items():
                full_key: str = f"system_attributes.{key}"
                if "bind_to" in value:
                    random_index: int = random.choice(
                        range(len(system_attributes[key]))
                    )
                    system_attribute[key] = system_attributes[key][random_index]
                    binding_index[value["bind_to"]] = random_index
                else:
                    random_index: int = random.choice(
                        range(len(system_attributes[key]))
                    )
                    system_attribute[key] = system_attributes[key][random_index]

            for key, value in config["user_attributes"]["user_profiles"].items():
                full_key: str = f"user_profiles.{key}"
                if "bind_to" in value and full_key in binding_index:
                    user_profile[key] = user_profiles[key][binding_index[full_key]]
                if "bind_to" not in value:
                    random_index: int = random.choice(range(len(user_profiles[key])))
                    user_profile[key] = user_profiles[key][random_index]
            # based on the user's profile, select the attribute
            strategy: str = (
                "react"  ## TODO: temporary strategy, need to set in the config later
            )
            attributes, matched_attribute_to_goal = pick_attributes(
                user_profile,
                augmented_attributes,
                config["user_attributes"]["goal"]["values"],
                strategy=strategy,
                client=config["client"],
            )
            doc_content: str = random.choice(documents)["content"] if documents else ""
            doc_snippet: str = truncate_string(doc_content, MAX_DOC_SNIPPET)
            doc: str = (
                "Here is a page from the company website: "
                # + random.choice(documents)["content"]
                + doc_snippet
                if documents
                else ""
            )
            user_profile_str: str = "Here is the your profile: " + "; ".join(
                f"{key}: {value}" for key, value in attributes.items()
            )
            goal: str = adapt_goal(
                goal=attributes["goal"],
                config=config,
                doc=doc,
                user_profile=user_profile_str,
            )
            attributes["goal"] = goal
            # get the proposed tool from the goal and the corresponding input as label
            # label, valid = get_label(attribute, config)

            labels_list.append(matched_attribute_to_goal)
            attributes_list.append(attributes)
            system_attributes_list.append(system_attribute)

    profiles, goals, system_inputs = convert_attributes_to_profiles(
        attributes_list, system_attributes_list, config
    )
    return profiles, goals, attributes_list, system_inputs, labels_list


def pick_goal(attributes, goals, strategy="react", client=None):
    """
    Pick the goal from the predefined attributes based on the user's profile
    """
    goal = ""
    if strategy == "llm_based":
        PICK_GOAL_PROMPT = """Given the following user's attributes, please pick the most relevant goal from the given list of goals.
user's attributes:
{attributes}

Goals:
{goals}

Goal:
"""
        response = chatgpt_chatbot(
            [
                {
                    "role": "user",
                    "content": PICK_GOAL_PROMPT.format(
                        goals="\n".join(goals), attributes=attributes
                    ),
                }
            ],
            client=client,
        )
        goal = response.split("Goal:")[1].strip()
        print("goal: ", goal)

    elif strategy == "react":
        PICK_GOAL_PROMPT = """Given the following user's attributes, please pick the most relevant goal from the given list of goals. First, generate a Thought about the reason why you pick this goal. Then, generate the final decided one attribute.
user's attributes:
{attributes}

Goals:
{goals}

Format:

Thought:
<the thought>

Goal:
<the picked goal>
"""
        response = chatgpt_chatbot(
            [
                {
                    "role": "user",
                    "content": PICK_GOAL_PROMPT.format(
                        goals="\n".join(goals), attributes=attributes
                    ),
                }
            ],
            client=client,
        )
        thought = response.split("Thought:")[1].split("Goal:")[0].strip()
        print("thought: ", thought)
        goal = response.split("Goal:")[1].strip()
        print("goal: ", goal)

    else:
        raise ValueError("Invalid strategy")
    return goal


def find_matched_attribute(
    goal, user_profile_str, strategy="react", client=None
) -> str:
    """
    Find the matched attribute for a given goal from the user's profile.

    This function attempts to identify the most relevant attribute category and its corresponding values
    from the user's profile that align with the specified goal.

    Args:
        goal (str): The user's goal that needs to be achieved.
        user_profile_str (str): A string representation of the user's full attributes.
        strategy (str, optional): The strategy to use for finding the matched attribute. Defaults to "react".

    Returns:
        str: The matched attribute value that is most relevant to the goal.
    """

    if strategy == "react":
        FIND_MATCHED_ATTRIBUTE_PROMPT = """Given the following goal, please find the most relevant attribute category and its corresponding values(it can come from the user's information, product information or other user's persona) from the full attributes that user need to provide to the assistant in order to let the assistant achieve the goal. First, generate a thought about the reason why you pick this attribute category and its corresponding values. Then, generate the final decided one attribute value. Please only return single attribute value.
For example, 
########################################################
1. 
Goal: interested in product information
Full attributes:
user_info: {{'id': 'gid://shopify/Customer/8740759797990', 'firstName': 'Yunan', 'lastName': 'Lu', 'email': 'yl4021@columbia.edu', 'phone': None, 'createdAt': '2025-03-23T02:47:38Z', 'updatedAt': '2025-03-29T21:01:02Z', 'numberOfOrders': '0', 'orders': {{'edges': []}}, 'amountSpent': {{'amount': '0.0', 'currencyCode': 'USD'}}, 'lastOrder': None, 'addresses': []}}
current_webpage: Product ID: gid://shopify/Product/8970006790374
Title: Pink Unicorn Boys & Girls Baseball Hat with Adjustable Buckle (One Size Fits Most)
Description: 𝐄𝐘𝐄-𝐂𝐀𝐓𝐂𝐇𝐈𝐍𝐆 – The Awhale Girl's Unicorn Baseball Hat stands out with a 3D design and graphics packed with a vibrant pink color and tons of personality. Your kid will not want to take it off! Add some magic to your child's wardrobe with this adorable baseball cap! 𝐏𝐄𝐑𝐅𝐄𝐂𝐓 𝐅𝐈𝐓 – Made for all girl's hair types, our hat contains 6 embroidered eyelets and a full back opening for those messy buns and ponytails. Designed to fit children ages 2-12, the adjustable buckle can be tweaked in seconds for toddlers or tweens! 𝐇𝐈𝐆𝐇-𝐐𝐔𝐀𝐋𝐈𝐓𝐘 – Made with Premium cotton, our girl's unicorn baseball hat stays stunning with machine-washable cotton twill and durable stitching that preserves the colors and personality of the hat. 𝐀𝐋𝐋-𝐃𝐀𝐘 𝐔𝐒𝐄 – Made with breathable material, our unicorn baseball hat is comfortable for outdoor activities like running, baseball, tennis, and golf but also perfect for casual wear at school, the park, or on a playdate! 𝐀𝐖𝐇𝐀𝐋𝐄 𝐁𝐑𝐀𝐍𝐃 – Welcome to AWHALE, where our designers are obsessed with combining High-Quality Materials and Chic Design to bring joy and laughter to boys and girls. Your child will love wearing our stylish outfits, and as everyone knows, there is nothing more adorable than a happy and fashionable child!
Total Inventory: 546
Options: [{{'name': 'Title', 'values': ['Default Title']}}]
The following are several variants of the product:
Variant name: Pink Unicorn Boys & Girls Baseball Hat with Adjustable Buckle (One Size Fits Most) - Default Title, Variant ID: gid://shopify/ProductVariant/45802049208550, Price: 19.99, Inventory Quantity: 546

product_experience_level: new to this product
customer_type: new prospect
persona: curious
current_webpage: about page
modality: text
communication_type: incoming
discovery_type: search engine results
buying_behavior: information gathering
budget: budget: low to moderate
Location: USA

Thought:
The user is interested in product information that they are looking at, so they probably have some question regarding the product's attribute, such as color, size, material, etc. In this case, the attribute category should be "product attribute" and the corresponding value can be color. 

Attribute:
product attribute: color

########################################################
2. 
Goal: return order
Full attributes:
user_info: {{'id': 'gid://shopify/Customer/8746986963174', 'firstName': 'two-orders', 'lastName': 'test-customer', 'email': 'two-orders-test@example.com', 'phone': None, 'createdAt': '2025-03-26T18:59:41Z', 'updatedAt': '2025-03-26T19:01:13Z', 'numberOfOrders': '2', 'orders': {{'edges': [{{'node': {{'id': 'gid://shopify/Order/6284126519526', 'name': '#1006', 'createdAt': '2025-03-26T19:00:09Z', 'cancelledAt': None, 'returnStatus': 'NO_RETURN', 'statusPageUrl': 'https://arklex-test-store.myshopify.com/73279963366/orders/7f635998c026a631847d1b5c68424234/authenticate?key=b63ae9312d8398e9b24df7b2b36aad4a', 'totalPriceSet': {{'presentmentMoney': {{'amount': '41.99'}}}}, 'fulfillments': [], 'lineItems': {{'edges': [{{'node': {{'id': 'gid://shopify/LineItem/15440574218470', 'title': 'Winter Flannel Blanket Solid Color Plaid Coral Blanket Fleece Bedspread For Bed Sofa Thicken Plush Blanket Thin Quilt Home Decor', 'quantity': 1, 'variant': {{'id': 'gid://shopify/ProductVariant/45802067525862', 'product': {{'id': 'gid://shopify/Product/8970009215206'}}}}}}}}]}}}}, {{'node': {{'id': 'gid://shopify/Order/6284127568102', 'name': '#1007', 'createdAt': '2025-03-26T19:01:12Z', 'cancelledAt': None, 'returnStatus': 'NO_RETURN', 'statusPageUrl': 'https://arklex-test-store.myshopify.com/73279963366/orders/6c2c4ee90b1befab9468978cbc1beb22/authenticate?key=510a7866400cfe4056f81a678ce9fdd9', 'totalPriceSet': {{'presentmentMoney': {{'amount': '16.99'}}}}, 'fulfillments': [], 'lineItems': {{'edges': [{{'node': {{'id': 'gid://shopify/LineItem/15440577298662', 'title': 'Inyahome New Art Velvet Yellow Blue Pink Solid Color Cushion Cover Pillow Cover Pillow Case Home Decorative Sofa Throw Decor', 'quantity': 1, 'variant': {{'id': 'gid://shopify/ProductVariant/45802063134950', 'product': {{'id': 'gid://shopify/Product/8970008461542'}}}}}}}}]}}}}}}]}}, 'amountSpent': {{'amount': '58.98', 'currencyCode': 'USD'}}, 'lastOrder': {{'id': 'gid://shopify/Order/6284127568102', 'name': '#1007'}}, 'addresses': [{{'id': 'gid://shopify/MailingAddress/9852296495334?model_name=CustomerAddress', 'firstName': 'two-orders', 'lastName': 'test-customer', 'company': '', 'address1': '2381 Dongan Pl', 'address2': '', 'city': 'New York', 'province': 'New York', 'country': 'United States', 'zip': '10040', 'phone': '+19999999999', 'name': 'two-orders test-customer', 'provinceCode': 'NY', 'countryCodeV2': 'US'}}]}}
current_webpage: Product ID: gid://shopify/Product/8970006855910
Title: White Rainbow Boys & Girls Baseball Hat with Adjustable Buckle(One Size Fits Most)
Description: 𝐄𝐘𝐄-𝐂𝐀𝐓𝐂𝐇𝐈𝐍𝐆 – The Awhale Girl's Unicorn Baseball Hat stands out with a 3D design and graphics packed with vibrant colors and tons of personality. Your kid will not want to take it off! Add some magic to your child's wardrobe with this adorable baseball cap! 𝐏𝐄𝐑𝐅𝐄𝐂𝐓 𝐅𝐈𝐓 – Made for all girl's hair types, our hat contains 6 embroidered eyelets and a full back opening for those messy buns and ponytails. Designed to fit children ages 2-12, the adjustable buckle can be tweaked in seconds for toddlers or tweens! 𝐇𝐈𝐆𝐇-𝐐𝐔𝐀𝐋𝐈𝐓𝐘 – Made with Premium cotton, our girl's unicorn baseball hat stays stunning with machine-washable cotton twill and durable stitching that preserves the colors and personality of the hat. 𝐀𝐋𝐋-𝐃𝐀𝐘 𝐔𝐒𝐄 – Made with breathable material, our unicorn baseball hat is comfortable for outdoor activities like running, baseball, tennis, and golf but also perfect for casual wear at school, the park, or on a playdate! 𝐀𝐖𝐇𝐀𝐋𝐄 𝐁𝐑𝐀𝐍𝐃 – Welcome to AWHALE, where our designers are obsessed with combining High-Quality Materials and Chic Design to bring joy and laughter to boys and girls. Your child will love wearing our stylish outfits, and as everyone knows, there is nothing more adorable than a happy and fashionable child!
Total Inventory: 499
Options: [{{'name': 'Title', 'values': ['Default Title']}}]
The following are several variants of the product:
Variant name: White Rainbow Boys & Girls Baseball Hat with Adjustable Buckle(One Size Fits Most) - Default Title, Variant ID: gid://shopify/ProductVariant/45802049372390, Price: 19.99, Inventory Quantity: 499

product_experience_level: new to this product
customer_type: returning customer
persona: neutral
current_webpage: product page
modality: browsing
communication_type: responsive
discovery_type: search engine results
buying_behavior: value-conscious
budget: value-conscious budget
purchase_history: home_decor_enthusiast
Location: New York City, NY, USA

Thought:
The user has placed two orders, so they are likely to return one of the orders. In order to do so, user need to provide the order id that they want to return.

Attribute:
Order id: gid://shopify/Order/6284126519526

########################################################
3. Goal: order tracking
Full attributes:
user_info: {{'id': 'gid://shopify/Customer/8728033657062', 'firstName': 'Xinyang', 'lastName': 'Wang', 'email': 'xinyang.wang@arklex.ai', 'phone': None, 'createdAt': '2025-03-19T16:02:24Z', 'updatedAt': '2025-04-11T15:29:35Z', 'numberOfOrders': '2', 'orders': {{'edges': [{{'node': {{'id': 'gid://shopify/Order/6294747119846', 'name': '#1014', 'createdAt': '2025-04-03T19:37:43Z', 'cancelledAt': None, 'returnStatus': 'NO_RETURN', 'statusPageUrl': 'https://arklex-test-store.myshopify.com/73279963366/orders/0b6fb2edceb8b38625db4cd4041d45a2/authenticate?key=e6a64953a5636a37733887a77a4835d2', 'totalPriceSet': {{'presentmentMoney': {{'amount': '31.99'}}}}, 'fulfillments': [], 'lineItems': {{'edges': [{{'node': {{'id': 'gid://shopify/LineItem/15461470961894', 'title': 'Bedding Set Solid Color Luxury Bedding Kit Rayon Satin Duvet Cover Set Twin Queen King Size Bed Set 2pcs/3pcs/4pcs', 'quantity': 1, 'variant': {{'id': 'gid://shopify/ProductVariant/45802057138406', 'product': {{'id': 'gid://shopify/Product/8970007970022'}}}}}}}}]}}}}, {{'node': {{'id': 'gid://shopify/Order/6294747807974', 'name': '#1015', 'createdAt': '2025-04-03T19:38:16Z', 'cancelledAt': '2025-04-03T19:40:33Z', 'returnStatus': 'NO_RETURN', 'statusPageUrl': 'https://arklex-test-store.myshopify.com/73279963366/orders/d76cae23bdc06689d3d7f4955978c966/authenticate?key=289ab7019d0e6ad3a0474e678618180b', 'totalPriceSet': {{'presentmentMoney': {{'amount': '15.99'}}}}, 'fulfillments': [], 'lineItems': {{'edges': [{{'node': {{'id': 'gid://shopify/LineItem/15461472436454', 'title': 'Green Boys & Girls Baseball Hat with Adjustable Buckle', 'quantity': 1, 'variant': {{'id': 'gid://shopify/ProductVariant/45802048487654', 'product': {{'id': 'gid://shopify/Product/8970006659302'}}}}}}}}]}}}}}}]}}, 'amountSpent': {{'amount': '31.99', 'currencyCode': 'USD'}}, 'lastOrder': {{'id': 'gid://shopify/Order/6294747807974', 'name': '#1015'}}, 'addresses': [{{'id': 'gid://shopify/MailingAddress/9835887526118?model_name=CustomerAddress', 'firstName': 'Xinyang', 'lastName': 'Wang', 'company': None, 'address1': '515 West 113th Street', 'address2': None, 'city': 'New York', 'province': 'New York', 'country': 'United States', 'zip': '10025', 'phone': None, 'name': 'Xinyang Wang', 'provinceCode': 'NY', 'countryCodeV2': 'US'}}]}}
current_webpage: Product ID: gid://shopify/Product/8970008953062
Title: Flower Plush Throw Pillow Soft Plant Cartoon Chair Cushion Living Bedroom Home Decorative Pillows Sofa Cushions Birthday Gifts
Description: Origin: CN(Origin)Type: Seat Cushion/Back CushionFeature: MemorySet Type: NoUnpick and Wash: Not Removable and WashablePattern: PRINTEDis_customized: NoStyle: MEDITERRANEANModel Number: P161Technics: KnittedShape: RoundPattern Type: cartoonFilling: CottonMaterial: Polyester / CottonAge Group: AdultsDimensions: 32-35cm/42-45cm/52-55cmWarning: 3 years and up
Total Inventory: 0
Options: [{{'name': 'Color', 'values': ['pink', 'green', 'Beige-pink corn', 'Beige-yellow corn', 'yellow', 'Beige-green corn']}}, {{'name': 'Specification', 'values': ['42-45cm', '52-55cm', '32-35cm']}}]
The following are several variants of the product:
Variant name: Flower Plush Throw Pillow Soft Plant Cartoon Chair Cushion Living Bedroom Home Decorative Pillows Sofa Cushions Birthday Gifts - pink / 42-45cm, Variant ID: gid://shopify/ProductVariant/45802066149606, Price: 18.99, Inventory Quantity: 0
Variant name: Flower Plush Throw Pillow Soft Plant Cartoon Chair Cushion Living Bedroom Home Decorative Pillows Sofa Cushions Birthday Gifts - pink / 52-55cm, Variant ID: gid://shopify/ProductVariant/45802066182374, Price: 24.99, Inventory Quantity: 0
Variant name: Flower Plush Throw Pillow Soft Plant Cartoon Chair Cushion Living Bedroom Home Decorative Pillows Sofa Cushions Birthday Gifts - green / 32-35cm, Variant ID: gid://shopify/ProductVariant/45802066215142, Price: 19.99, Inventory Quantity: 0

product_experience_level: new to this product
customer_type: recent customer
persona: explorative
current_webpage: product page
modality: visual
communication_type: digital_preference
discovery_type: search engine results
buying_behavior: value-conscious explorer
budget: low-budget
purchase_history: Explorative purchase history with a focus on home goods and occasional interest in apparel.
Location: New York City, NY, USA

Thought:
The user has placed two orders: gid://shopify/Order/6294747119846 and gid://shopify/Order/6294747807974, however gid://shopify/Order/6294747807974 has been cancelled, so the user want to track the other order.

Attribute:
Order id: gid://shopify/Order/6294747119846

########################################################
Goal: {goal}
Full attributes: 
{user_profile}

"""

        system_instruction = FIND_MATCHED_ATTRIBUTE_PROMPT.format(
            goal=goal, user_profile=user_profile_str
        )
        print(system_instruction)
        response = chatgpt_chatbot(
            [{"role": "user", "content": system_instruction}], client=client
        )
        thought = response.split("Thought:")[1].split("Attribute:")[0].strip()
        print("thought: ", thought)
        attribute = response.split("Attribute:")[1].strip()
        print("attribute: ", attribute)
    else:
        raise ValueError("Invalid strategy")
    return attribute


def pick_attributes(
    user_profile: Dict[str, Any],
    attributes: Dict[str, List[str]],
    goals: List[str],
    strategy: str = "react",
    client: Any = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Pick attributes for a user profile based on the strategy.

    Args:
        user_profile (dict): The existing user_profile from user_attributes.json file if exist. It can be empty.
        attributes (dict): The predefined user's attributes values
        goals (list): The predefined goal list.
        strategy (str, optional): The strategy to use for picking attributes. Defaults to "react".
        client (Any, optional): The client to use for the strategy. Defaults to None.

    Returns:
        tuple: A tuple containing the selected attributes and the matched attribute to goal.
    """
    if strategy == "react":
        return pick_attributes_react(user_profile, attributes, goals, client)
    else:
        return pick_attributes_random(user_profile, attributes, goals)


def pick_attributes_react(
    user_profile: Dict[str, Any],
    attributes: Dict[str, List[str]],
    goals: List[str],
    client: Any,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Pick attributes for a user profile using the react strategy.

    Args:
        user_profile (dict): The existing user_profile from user_attributes.json file if exist. It can be empty.
        attributes (dict): The predefined user's attributes values
        goals (list): The predefined goal list.
        client (Any): The client to use for the strategy.

    Returns:
        tuple: A tuple containing the selected attributes and the matched attribute to goal.
    """
    selected_attributes: Dict[str, Any] = {}
    matched_attribute_to_goal: Dict[str, Any] = {}

    # First, pick a goal
    goal: str = random.choice(goals)
    selected_attributes["goal"] = goal

    # Then, pick attributes for each category
    for category, values in attributes.items():
        if category == "goal":
            continue
        selected_attributes[category] = random.choice(values)

    # Find the matched attribute to goal
    matched_attribute_to_goal = find_matched_attribute(
        selected_attributes, goal, client
    )

    return selected_attributes, matched_attribute_to_goal


def pick_attributes_random(
    user_profile: Dict[str, Any],
    attributes: Dict[str, List[str]],
    goals: List[str],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Pick attributes for a user profile using the random strategy.

    Args:
        user_profile (dict): The existing user_profile from user_attributes.json file if exist. It can be empty.
        attributes (dict): The predefined user's attributes values
        goals (list): The predefined goal list.

    Returns:
        tuple: A tuple containing the selected attributes and the matched attribute to goal.
    """
    selected_attributes: Dict[str, Any] = {}
    matched_attribute_to_goal: Dict[str, Any] = {}

    # First, pick a goal
    goal: str = random.choice(goals)
    selected_attributes["goal"] = goal

    # Then, pick attributes for each category
    for category, values in attributes.items():
        if category == "goal":
            continue
        selected_attributes[category] = random.choice(values)

    # Find the matched attribute to goal
    matched_attribute_to_goal = find_matched_attribute(selected_attributes, goal, None)

    return selected_attributes, matched_attribute_to_goal


def find_matched_attribute(
    attributes: Dict[str, Any], goal: str, client: Any
) -> Dict[str, Any]:
    """
    Find the matched attribute to goal.

    Args:
        attributes (dict): The selected attributes.
        goal (str): The selected goal.
        client (Any): The client to use for the strategy.

    Returns:
        dict: The matched attribute to goal.
    """
    matched_attribute_to_goal: Dict[str, Any] = {}
    matched_attribute_to_goal["goal"] = goal
    matched_attribute_to_goal["matched_attribute"] = attributes

    return matched_attribute_to_goal


def adapt_goal(goal: str, config: Dict[str, Any], doc: str, user_profile: str) -> str:
    """
    Adapt the goal based on the company information and user profile.

    Args:
        goal (str): The original goal.
        config (dict): The configuration.
        doc (str): The company document.
        user_profile (str): The user profile.

    Returns:
        str: The adapted goal.
    """
    prompt: str = ADAPT_GOAL.format(
        goal=goal,
        company_summary=config["company_summary"],
        doc=doc,
        user_profile=user_profile,
    )
    # adapted_goal: str = chatgpt_chatbot(prompt, config["client"])
    adapted_goal: str = chatgpt_chatbot(
        [{"role": "user", "content": prompt}], config["client"]
    )
    return adapted_goal


def get_custom_profiles(config) -> tuple[dict, dict]:
    """Fetch custom user and system profiles from the configuration.

    This function retrieves custom profiles for both user and system attributes
    based on the provided configuration. It handles API calls to fetch data from database
    and manages bindings between system and user attributes.

    Args:
        config (dict): Configuration dictionary containing user and system attributes
                       with potential API endpoints and binding information.

    Returns:
        tuple[dict, dict]: A tuple containing two dictionaries:
                           - user_profiles: Custom user profiles with resolved bindings.
                           - system_attributes: Custom system attributes with resolved bindings.
    """

    if (
        "system_attributes" in config["user_attributes"]
        and "user_profiles" in config["user_attributes"]
    ):
        # First, get system attributes with bindings
        system_attributes = {}
        bindings = {}  # Track bindings between fields

        # Process system_attributes and their bindings
        for key, value in config["user_attributes"]["system_attributes"].items():
            full_key = f"system_attributes.{key}"
            if isinstance(value, dict):
                api_url = value.get("api")
                response = requests.get(api_url).json()
                system_attributes[key] = response
                # Track bindings if they exist
                if "bind_to" in value:
                    bindings[full_key] = response
                    bindings[value["bind_to"]] = response
            else:
                system_attributes[key] = value

        user_profiles = {}
        # Process user_profiles and their bindings
        for key, value in config["user_attributes"]["user_profiles"].items():
            if isinstance(value, dict):
                if "bind_to" in value and value["bind_to"] in bindings:
                    user_profiles[key] = bindings[value["bind_to"]]
                else:
                    api_url = value.get("api")
                    response = requests.get(api_url).json()
                    user_profiles[key] = response
            else:
                user_profiles[key] = value

    return user_profiles, system_attributes


def get_label(attribute, config):
    """
    Get the appropriate tool used by the Agent to achieve the user's goal
    """
    valid = True  # dummy variable
    GET_TOOL_PROMPT = """Given the list of tools that an AI assistant can use, and the user's goal, return the tool that is most likely to be used to achieve the goal. Only return the tool id.
    Tools: {tools}
    User's goal: {goal}
    Tool_id:
    """
    env = Env(tools=config["tools"], workers=config["workers"])
    tool_list = []
    for tool in config["tools"]:
        tool_id = tool["id"]
        tool: Tool = env.tools[tool_id]["execute"]()
        slots = tool.slots
        tool_description = tool.description
        tool_input = [s.model_dump() for s in slots]
        tool_output = tool.output
        tool_list.append(
            {
                "tool_id": tool_id,
                "tool_description": tool_description,
                "tool_input": tool_input,
                "tool_output": tool_output,
            }
        )
    tool_list.append(
        {
            "tool_id": "0",
            "tool_description": "There are no tools appropriate for the goal.",
            "tool_input": [],
            "tool_output": "There are no tools appropriate for the goal.",
        }
    )

    label = [
        {
            "tool_id": "0",
            "tool_name": "No tool",
            "slots": {},
        }
    ]
    attempt = 0
    while attempt < 3:
        try:
            response = chatgpt_chatbot(
                [
                    {
                        "role": "system",
                        "content": GET_TOOL_PROMPT.format(
                            tools="\n".join(
                                f"tool_id: {tool['tool_id']}\ntool_description: {tool['tool_description']}\ntool_input: {tool['tool_input']}\ntool_output: {tool['tool_output']}"
                                for tool in tool_list
                            ),
                            goal=attribute["goal"],
                        ),
                    }
                ],
                config["client"],
            )
            pred_tool_id = response
            if pred_tool_id == "0":
                break
            selected_tool = env.tools[pred_tool_id]["execute"]()
            slots = selected_tool.slots
            pred_slots = SlotFilling(url="").execute(
                slots, str(attribute), type="user_simulator"
            )
            pred_slots_dict = {slot.name: slot.value for slot in pred_slots}
            label = [
                {
                    "tool_id": pred_tool_id,
                    "tool_name": selected_tool.name,
                    "slots": pred_slots_dict,
                }
            ]
            break
        except Exception as e:
            attempt += 1

    return label, valid


def filter_attributes(config) -> dict:
    """Filter out the attributes from the predefinted user_attributes.json based on the customer_type

    Args:
        config (dict): _description_

    Returns:
        dict: filtered attributes based on the customer_type
    """
    filtered_attributes = {}
    for key in config["user_attributes"].keys():
        if key == "generic" or key == config["synthetic_data_params"]["customer_type"]:
            for subkey in config["user_attributes"][key].keys():
                filtered_attributes[subkey] = config["user_attributes"][key][subkey]
    return filtered_attributes


def select_system_attributes(config, synthetic_data_params) -> list[dict[str, dict]]:
    system_attributes = []
    for subkey, subvalue in config["user_attributes"]["system_attributes"].items():
        if isinstance(subvalue, dict):
            api_url = subvalue.get("api")
            response = requests.get(api_url).json()
            config["user_attributes"]["system_attributes"][subkey] = response

    for i in range(synthetic_data_params["num_convos"]):
        system_attribute = {}
        for subkey, subvalue in config["user_attributes"]["system_attributes"].items():
            if isinstance(subvalue, list) and isinstance(subvalue[0], dict):
                system_attribute[subkey] = random.choice(subvalue)
            else:
                raise ValueError("System attributes should be a list of dictionaries")
        system_attributes.append(copy.deepcopy(system_attribute))
    return system_attributes


def augment_attributes(
    attributes: dict[str, dict[str, any]], config: dict, documents: list
) -> dict[str, list]:
    """Augment the attribute that without predefined values based on the company's summary and documents

    Args:
        attributes (dict(str, dict(str, Any))): the predefined attributes in the user_attributes.json
        config (dict): the config to provide company's summary
        documents (list): the company's documents

    Returns:
        dict(str, list): the augmented attributes
    """
    text_attribute = ""
    for key, value in attributes.items():
        if len(value["values"]) == 0:
            continue
        text_attribute += f"{key}: {value['values']}\n"

    new_attrs = {}
    for category in attributes.keys():
        if not attributes[category]["generate_values"]:
            new_attrs[category] = attributes[category]["values"]
        else:
            if documents:
                doc_content: str = random.choice(documents).get("content", "")
                doc_snippet: str = truncate_string(doc_content, MAX_DOC_SNIPPET)
                attrs = chatgpt_chatbot(
                    [
                        {
                            "role": "user",
                            "content": ADD_ATTRIBUTES.format(
                                user_profile=text_attribute,
                                category=category,
                                company_summary=config["intro"],
                                # company_doc=random.choice(documents),
                                company_doc=doc_snippet,
                            ),
                        }
                    ],
                    config["client"],
                )
            else:
                attrs = chatgpt_chatbot(
                    [
                        {
                            "role": "user",
                            "content": ADD_ATTRIBUTES_WO_DOC.format(
                                user_profile=text_attribute,
                                category=category,
                                company_summary=config["intro"],
                            ),
                        }
                    ],
                    config["client"],
                )
            new_attrs[category] = attrs.split(", ")
    return new_attrs


def attributes_to_text(attribute_list):
    text_attributes = []
    for item in attribute_list:
        text_attribute = ""
        for key, value in item.items():
            text_attribute += f"{key}: {value}\n"
        text_attributes.append(text_attribute[:-1])
    return text_attributes


def convert_attributes_to_profiles(
    attributes_list: List[Dict[str, Any]],
    system_attributes_list: List[Dict[str, Any]],
    config: Dict[str, Any],
) -> Tuple[List[str], List[str], List[Dict[str, Any]]]:
    """
    Convert attributes to profiles.

    Args:
        attributes_list (list): The list of attributes.
        system_attributes_list (list): The list of system attributes.
        config (dict): The configuration.

    Returns:
        tuple: A tuple containing the profiles, goals, and system inputs.
    """
    profiles: List[str] = []
    goals: List[str] = []
    system_inputs: List[Dict[str, Any]] = []

    for attributes, system_attributes in zip(attributes_list, system_attributes_list):
        profile: str = convert_attributes_to_profile(attributes, config)
        profiles.append(profile)
        goals.append(attributes["goal"])
        system_inputs.append(system_attributes)

    return profiles, goals, system_inputs


def convert_attributes_to_profile(
    attributes: Dict[str, Any], config: Dict[str, Any]
) -> str:
    """
    Convert attributes to a profile.

    Args:
        attributes (dict): The attributes.
        config (dict): The configuration.

    Returns:
        str: The profile.
    """
    user_attr: str = "; ".join(f"{key}: {value}" for key, value in attributes.items())
    prompt: str = ATTR_TO_PROFILE.format(
        company_summary=config["company_summary"], user_attr=user_attr
    )
    # profile: str = chatgpt_chatbot(prompt, config["client"])
    profile: str = chatgpt_chatbot(
        [{"role": "user", "content": prompt}], config["client"]
    )
    return profile


def build_labelled_profile(
    synthetic_data_params: Dict[str, Any], config: Dict[str, Any]
) -> Tuple[
    List[str],
    List[str],
    List[Dict[str, Any]],
    List[Dict[str, Any]],
    List[Dict[str, Any]],
]:
    """
    Build labelled profiles.

    Args:
        synthetic_data_params (dict): The synthetic data parameters.
        config (dict): The configuration.

    Returns:
        tuple: A tuple containing the profiles, goals, attributes list, system inputs, and labels list.
    """
    profiles: List[str] = []
    goals: List[str] = []
    attributes_list: List[Dict[str, Any]] = []
    system_inputs: List[Dict[str, Any]] = []
    labels_list: List[Dict[str, Any]] = []

    # Load documents
    documents: List[Dict[str, str]] = load_docs(
        config["documents_dir"], config, synthetic_data_params["num_goals"] * 2
    )

    # Filter attributes
    predefined_attributes: Dict[str, Dict[str, Any]] = filter_attributes(config)

    # Augment attributes
    augmented_attributes: Dict[str, List[str]] = augment_attributes(
        predefined_attributes, config, documents
    )

    # Build profiles
    for i in range(synthetic_data_params["num_convos"]):
        # Pick attributes
        attributes, matched_attribute_to_goal = pick_attributes(
            {},
            augmented_attributes,
            config["user_attributes"]["goal"]["values"],
            "react",
            config["client"],
        )

        # Adapt goal
        doc_content: str = random.choice(documents)["content"] if documents else ""
        doc_snippet: str = truncate_string(doc_content, MAX_DOC_SNIPPET)
        doc: str = (
            "Here is a page from the company website: "
            # + random.choice(documents)["content"]
            + doc_snippet
            if documents
            else ""
        )
        user_profile_str: str = "Here is the your profile: " + "; ".join(
            f"{key}: {value}" for key, value in attributes.items()
        )
        goal: str = adapt_goal(
            goal=attributes["goal"],
            config=config,
            doc=doc,
            user_profile=user_profile_str,
        )
        attributes["goal"] = goal

        # Convert attributes to profile
        profile: str = convert_attributes_to_profile(attributes, config)

        # Append results
        profiles.append(profile)
        goals.append(goal)
        attributes_list.append(attributes)
        system_inputs.append({})
        labels_list.append(matched_attribute_to_goal)

    return profiles, goals, attributes_list, system_inputs, labels_list


# def filter_attributes(config: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
#     """
#     Filter attributes from the configuration.
#
#     Args:
#         config (dict): The configuration.
#
#     Returns:
#         dict: The filtered attributes.
#     """
#     predefined_attributes: Dict[str, Dict[str, Any]] = {}
#     for key, value in config["user_attributes"].items():
#         if key != "goal" and key != "system_attributes":
#             predefined_attributes[key] = value
#     return predefined_attributes


# def augment_attributes(
#     predefined_attributes: Dict[str, Dict[str, Any]],
#     config: Dict[str, Any],
#     documents: List[Dict[str, str]],
# ) -> Dict[str, List[str]]:
#     """
#     Augment attributes with additional values.
#
#     Args:
#         predefined_attributes (dict): The predefined attributes.
#         config (dict): The configuration.
#         doc (str): The company document.
#
#     Returns:
#         dict: The augmented attributes.
#     """
#     augmented_attributes: Dict[str, List[str]] = {}
#     for category, values in predefined_attributes.items():
#         augmented_attributes[category] = values["values"]
#         if "augment" in values and values["augment"]:
#             doc_content: str = random.choice(documents)["content"] if documents else ""
#             doc_snippet: str = truncate_string(doc_content, MAX_DOC_SNIPPET)
#             doc: str = (
#                 "Here is a page from the company website: "
#                 + random.choice(documents)["content"]
#                 + doc_snippet
#                 if documents
#                 else ""
#             )
#             prompt: str = ADD_ATTRIBUTES.format(
#                 user_profile="; ".join(
#                     f"{key}: {value}" for key, value in predefined_attributes.items()
#                 ),
#                 category=category,
#                 company_summary=config["company_summary"],
#                 company_doc=doc,
#             )
#             response: str = chatgpt_chatbot(prompt, config["client"])
#             response: str = chatgpt_chatbot(
#                 [{"role": "user", "content": prompt}], config["client"]
#             )
#             new_values: List[str] = [value.strip() for value in response.split(",")]
#             augmented_attributes[category].extend(new_values)
#     return augmented_attributes
#
#
# def get_custom_profiles(
#     config: Dict[str, Any],
# ) -> Tuple[Dict[str, List[str]], Dict[str, List[str]]]:
#     """
#     Get custom profiles from the configuration.
#
#     Args:
#         config (dict): The configuration.
#
#     Returns:
#         tuple: A tuple containing the user profiles and system attributes.
#     """
#     user_profiles: Dict[str, List[str]] = {}
#     system_attributes: Dict[str, List[str]] = {}
#
#     for key, value in config["user_attributes"]["user_profiles"].items():
#         user_profiles[key] = value["values"]
#
#     for key, value in config["user_attributes"]["system_attributes"].items():
#         system_attributes[key] = value["values"]
#
#     return user_profiles, system_attributes


# def select_system_attributes(
#     config: Dict[str, Any], synthetic_data_params: Dict[str, Any]
# ) -> List[Dict[str, Any]]:
#     """
#     Select system attributes from the configuration.
#
#     Args:
#         config (dict): The configuration.
#         synthetic_data_params (dict): The synthetic data parameters.
#
#     Returns:
#         list: The selected system attributes.
#     """
#     system_attributes: List[Dict[str, Any]] = []
#     for i in range(synthetic_data_params["num_convos"]):
#         system_attribute: Dict[str, Any] = {}
#         for key, value in config["user_attributes"]["system_attributes"].items():
#             system_attribute[key] = random.choice(value["values"])
#         system_attributes.append(system_attribute)
#     return system_attributes
